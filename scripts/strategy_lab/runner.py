"""Run registered experiments, archive every result and rank only development."""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import subprocess
import time

import numpy as np
import pandas as pd

from .data import PROJECT, RESEARCH, load_panel
from .engine import simulate
from .rules import targets


def summary(rows, baseline, cohort):
    b = {r['code']: r for r in baseline}
    selected = [r for r in rows if r['code'] in b and (cohort == 'all' or r[cohort])]
    if not selected:
        return {'count': 0}
    med = lambda values: float(np.median(values)) if values else None
    excess = [r['cagr_pct']-b[r['code']]['cagr_pct'] for r in selected]
    sharpe_pairs = [(r['sharpe'], b[r['code']]['sharpe']) for r in selected
                    if r['sharpe'] is not None and b[r['code']]['sharpe'] is not None]
    return dict(count=len(selected), median_cagr=med([r['cagr_pct'] for r in selected]),
                median_total_return=med([r['total_return_pct'] for r in selected]),
                median_excess_cagr=med(excess), outperform_rate=sum(x > 1e-8 for x in excess)/len(selected),
                median_sharpe=med([r['sharpe'] for r in selected if r['sharpe'] is not None]),
                median_sharpe_excess=med([a-bb for a, bb in sharpe_pairs]),
                higher_sharpe_rate=sum(a > bb+1e-10 for a, bb in sharpe_pairs)/len(sharpe_pairs) if sharpe_pairs else None,
                sharpe_pairs=len(sharpe_pairs), median_drawdown=med([r['drawdown_pct'] for r in selected]),
                median_exposure=med([r['invested_fraction'] for r in selected]),
                median_entries=med([r['entries'] for r in selected]),
                activity_rate=sum(r['entries'] > 0 for r in selected)/len(selected),
                all_cash=sum(r['all_cash'] for r in selected),
                cagr8_rate=sum(r['cagr_pct'] >= 8 for r in selected)/len(selected),
                positive_rate=sum(r['total_return_pct'] > 0 for r in selected)/len(selected))


def rank_completed():
    all_rows = []
    for file in sorted((RESEARCH/'results').glob('round*-summary.json')):
        for r in json.loads(file.read_text(encoding='utf-8'))['candidates']:
            m = r['windows']['development']['primary']
            all_rows.append(dict(id=r['id'], family=r['family'], round=file.stem.split('-')[0], **m))
    if not all_rows:
        return []
    frame = pd.DataFrame(all_rows).drop_duplicates('id', keep='last')
    weights = {'outperform_rate': .35, 'median_sharpe': .30, 'median_cagr': .20, 'median_excess_cagr': .15}
    frame['score'] = 0.
    for field, weight in weights.items():
        values = frame[field].fillna(-1e12)
        rank = values.rank(method='average')
        component = (rank-1)/(len(frame)-1)*100 if len(frame) > 1 else 50.
        frame['score'] += component*weight
    frame['eligible'] = (frame.activity_rate >= .8) & (frame.family != 'buy_hold')
    frame = frame.sort_values(['eligible', 'score', 'median_drawdown', 'id'], ascending=[False, False, True, True])
    frame.to_csv(RESEARCH/'results/development-leaderboard.csv', index=False, encoding='utf-8-sig')
    return json.loads(frame.to_json(orient='records'))


def deadline_check(protocol, reserve=0):
    end = dt.datetime.fromisoformat(protocol['deadline_utc'].replace('Z', '+00:00'))
    if (end-dt.datetime.now(dt.timezone.utc)).total_seconds() <= reserve:
        raise TimeoutError('Two-hour research deadline reached; preserve completed records and stop.')


def run_round(name):
    protocol = json.loads((RESEARCH/'protocol.json').read_text(encoding='utf-8'))
    deadline_check(protocol, 60)
    config_file = RESEARCH/'candidates'/f'{name}.json'
    config = json.loads(config_file.read_text(encoding='utf-8'))
    output = RESEARCH/'results'
    output.mkdir(exist_ok=True)
    final = output/f'{name}-summary.json'
    if final.exists():
        raise FileExistsError(f'Immutable round already exists: {final}')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip()
    tracked_diff = subprocess.check_output(['git', 'diff', 'HEAD', '--', 'scripts/strategy_lab', 'scripts/run_strategy_lab.py', str(config_file)], cwd=PROJECT, text=True)
    if tracked_diff:
        raise RuntimeError('Commit source and candidate changes before running an archived experiment.')
    panel = load_panel()
    manifest = {'prices': panel.manifest, 'exclusions': panel.exclusions,
                'universe_sha256': hashlib.sha256((PROJECT/'data/connect-10y-2026-09-06/universe.json').read_bytes()).hexdigest()}
    manifest_file = RESEARCH/'input-manifest.json'
    if manifest_file.exists():
        assert json.loads(manifest_file.read_text(encoding='utf-8')) == manifest
    else:
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    benchmark_target = targets(panel, {'family': 'buy_hold'})
    benchmarks = {k: simulate(panel, benchmark_target, protocol[k])['rows'] for k in ('training', 'development')}
    package = dict(round=name, source_commit=commit,
                   started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   protocol_sha256=hashlib.sha256((RESEARCH/'protocol.json').read_bytes()).hexdigest(),
                   config_sha256=hashlib.sha256(config_file.read_bytes()).hexdigest(),
                   input_manifest_sha256=hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
                   benchmark={w: {c: summary(rows, rows, c) for c in ('all','primary','full10')}
                              for w, rows in benchmarks.items()}, candidates=[])
    details = []
    started = time.monotonic()
    for i, spec in enumerate(config['candidates'], 1):
        deadline_check(protocol, 60)
        target = targets(panel, spec)
        item = dict(**spec, windows={})
        for window in ('training', 'development'):
            sim = simulate(panel, target, protocol[window])
            rows = sim['rows']
            item['windows'][window] = {c: summary(rows, benchmarks[window], c) for c in ('all','primary','full10')}
            baseline = {r['code']: r for r in benchmarks[window]}
            for r in rows:
                b = baseline[r['code']]
                details.append(dict(candidate=spec['id'], window=window, **r, benchmark_cagr=b['cagr_pct'],
                                    benchmark_sharpe=b['sharpe'], excess_cagr=r['cagr_pct']-b['cagr_pct']))
        package['candidates'].append(item)
        m = item['windows']['development']['primary']
        print(f"{name} {i}/{len(config['candidates'])} {spec['id']}: n={m['count']} win={m['outperform_rate']:.1%} CAGR={m['median_cagr']:.2f}% Sharpe={m['median_sharpe']} active={m['activity_rate']:.1%} {time.monotonic()-started:.0f}s", flush=True)
        # Crash recovery remains local until a complete round is archived.
        recovery = PROJECT/'outputs/strategy-loop-recovery.json'
        recovery.parent.mkdir(exist_ok=True)
        recovery.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding='utf-8')
    package['completed_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    if hasattr(panel, 'aux_manifest'):
        package['additional_snapshot_inputs'] = panel.aux_manifest
        package['fundamental_warning'] = 'Snapshot GAAP proxy, assumed lag, not original disclosure vintages; missing fields use explicitly specified technical fallback.'
    package['elapsed_seconds'] = time.monotonic()-started
    final.write_text(json.dumps(package, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=list(details[0]))
    writer.writeheader()
    writer.writerows(details)
    (output/f'{name}-stocks.csv.gz').write_bytes(gzip.compress(text.getvalue().encode('utf-8-sig'), mtime=0))
    ranked = rank_completed()
    print('LEADERS', json.dumps([{k:r[k] for k in ['id','score','eligible','outperform_rate','median_cagr','median_sharpe']} for r in ranked[:8]], ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', required=True)
    args = parser.parse_args()
    run_round(args.round)
