"""Lagged snapshot fundamentals: explicitly exploratory, not a PIT database."""
import datetime as dt
import hashlib
import json

import numpy as np

from .data import PROJECT


def annual_values(dates, annual, lag):
    """Select fiscal priority strictly after assumed availability, never future FY."""
    rows = []
    for day in dates:
        d = dt.date.fromisoformat(day)
        visible = [(a, dt.date.fromisoformat(a['year_end'])+dt.timedelta(days=lag)) for a in annual
                   if dt.date.fromisoformat(a['year_end'])+dt.timedelta(days=lag) < d]
        a, available = max(visible, key=lambda x: x[0]['year_end']) if visible else (None, None)
        if a is None or (d-available).days > 400:
            rows.append((np.nan,np.nan,np.nan,np.nan))
            continue
        value = lambda k: float(a[k]) if isinstance(a.get(k),(int,float)) and np.isfinite(a[k]) else np.nan
        rows.append((value('profit'),value('revenue_yoy_pct'),value('profit_yoy_pct'),value('margin_pct')))
    return np.array(rows)


def features(panel, lag=180):
    key=('fundamentals',lag)
    if key in panel.cache:
        return panel.cache[key]
    base=PROJECT/'data/connect-fundamentals-2026-09-06/prepared'
    matrices={k:np.full(panel.shape,np.nan) for k in ['profit','revenue_growth','profit_growth','margin']}
    inputs=[]
    monthly=panel.review('monthly')
    for j,stock in enumerate(panel.stocks):
        file=base/(stock['code']+'.json')
        if not file.exists():
            continue
        record=json.loads(file.read_text(encoding='utf-8'))
        inputs.append(dict(file=file.relative_to(PROJECT).as_posix(),sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
        ix=np.flatnonzero(monthly[:,j])
        values=annual_values(panel.dates[ix].tolist(),record['annual'],lag)
        # Carry the complete current review, including missing fields. Do not ffill
        # individual fundamentals, which would silently reuse a stale older FY.
        for z,start in enumerate(ix):
            stop=ix[z+1] if z+1<len(ix) else panel.shape[0]
            for k,value in zip(matrices,values[z]):
                matrices[k][start:stop,j]=value
    panel.cache[key]=matrices
    panel.aux_manifest=inputs
    return matrices
