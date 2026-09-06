"""Resume a dated Stock Connect scan using the existing Rust strategy engines."""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--universe', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--skip-download', action='store_true', help='Recompute only verified cached prices')
    args = parser.parse_args()
    universe = json.loads(pathlib.Path(args.universe).read_text(encoding='utf-8'))
    out = pathlib.Path(args.output_root).resolve()
    for folder in ['prices', 'signals', 'rankings', 'logs']:
        (out / folder).mkdir(parents=True, exist_ok=True)
    cli = ROOT / 'target/release/financial_projects.exe'
    signals = ROOT / 'target/release/examples/latest_signals.exe'

    def run(command, timeout=90):
        result = subprocess.run([str(x) for x in command], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError((result.stderr + result.stdout).strip())
        return result.stdout + result.stderr

    def one(stock):
        code = f"{int(stock['code']):04d}"
        prices = out / 'prices' / f'{code}.HK.csv'
        snapshot = out / 'signals' / f'{code}.HK.json'
        ranking = out / 'rankings' / f'{code}.HK.csv'
        log = []
        try:
            if not prices.exists():
                if args.skip_download:
                    previous = out / 'signals' / f'{code}.result.json'
                    reason = json.loads(previous.read_text(encoding='utf-8')).get('error', '') if previous.exists() else ''
                    raise RuntimeError('No verified price history. ' + reason)
                for attempt in range(3):
                    try:
                        log.append(run([cli, 'data', 'download', '--symbol', code,
                                        '--years', '5', '--format', 'csv',
                                        '--output-dir', out / 'prices']))
                        if not prices.exists():
                            raise RuntimeError('No price file returned')
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(2 * (attempt + 1))
            log.append(run([signals, '--data-dir', out / 'prices', '--symbol', code,
                            '--output', snapshot]))
            data = json.loads(snapshot.read_text(encoding='utf-8'))[0]
            if len(data['strategies']) != 20:
                raise RuntimeError('Expected exactly 20 strategy presets')
            log.append(run([cli, 'compare', '--symbol', code, '--data-dir', out / 'prices',
                            '--rank', '--format', 'csv', '--output', ranking]))
            with ranking.open(encoding='utf-8', newline='') as file:
                ranks = list(csv.DictReader(file))
            if len(ranks) != 20:
                raise RuntimeError('Expected exactly 20 ranked strategy rows')
            key = lambda name, params: (name, json.dumps(params, sort_keys=True))
            lookup = {key(r['strategy'], json.loads(r['params_json'])): r for r in ranks}
            for strategy in data['strategies']:
                strategy['historical'] = lookup[key(strategy['strategy_name'], strategy['params'])]
            result = dict(stock=stock, status='ok', snapshot=data,
                          price_sha256=hashlib.sha256(prices.read_bytes()).hexdigest())
        except Exception as exc:
            result = dict(stock=stock, status='error', error=str(exc))
            log.append(str(exc))
        (out / 'logs' / f'{code}.txt').write_text('\n'.join(log), encoding='utf-8')
        (out / 'signals' / f'{code}.result.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    results = []
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one, s): s for s in universe['selected']}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            count = len(results)
            if count % 20 == 0 or result['status'] != 'ok' or count == len(futures):
                print(f"{count}/{len(futures)} completed, "
                      f"errors={sum(r['status'] != 'ok' for r in results)}, "
                      f"elapsed={time.monotonic()-started:.0f}s, "
                      f"last={result['stock']['code']} {result['status']}", flush=True)
    results.sort(key=lambda r: r['stock']['code'])
    (out / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Wrote {len(results)} results to {out / 'results.json'}", flush=True)


if __name__ == '__main__':
    main()
