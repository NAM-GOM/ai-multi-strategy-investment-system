"""Validate, preview and package W02 outputs after the diagnostic cycle finishes."""
import json
import re
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import pandas as pd
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .w02 import svg_chart
from .w02_stage0 import ROOT, frozen_files, sha

def raster_preview(path):
    # The cycle's SVGs contain only text/rect/line. Preserve every coordinate and label.
    root = ET.parse(path).getroot()
    width, height = int(root.attrib['width']), int(root.attrib['height'])
    im = Image.new('RGB', (width,height), 'white')
    draw = ImageDraw.Draw(im)
    def visit(node, style):
        a = dict(style, **node.attrib)
        tag = node.tag.split('}')[-1]
        def n(k,default=0): return float(a.get(k,default))
        if tag == 'rect':
            w = width if a.get('width')=='100%' else n('width')
            h = height if a.get('height')=='100%' else n('height')
            draw.rectangle([n('x'),n('y'),n('x')+w,n('y')+h], fill=a.get('fill','black'),
                           outline=a.get('stroke'), width=int(n('stroke-width',1)))
        elif tag=='line':
            draw.line([n('x1'),n('y1'),n('x2'),n('y2')],fill=a.get('stroke','black'),width=int(n('stroke-width',1)))
        elif tag=='text':
            font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',int(n('font-size',16)))
            draw.text((n('x'),n('y')),node.text or '',font=font,fill=a.get('fill','black'),anchor='ls')
        for child in node: visit(child,a)
    visit(root,{})
    im.save(path.with_suffix('.png'))

def main():
    assert (ROOT/'W02_report.md').exists(), 'Cycle must finish before finalization'
    required=['W02_summary.csv','baseline_reproduction.csv','trade_diagnostics.csv','asset_contribution.csv',
              'calendar_metrics.csv','T1_ema_sensitivity.csv','T2_donchian_sensitivity.csv',
              'T3_tsmom_sensitivity.csv','stop_sensitivity.csv','cost_stress.csv']
    frames={n:pd.read_csv(ROOT/n) for n in required}
    assert frames['baseline_reproduction.csv'].passed.all()
    assert len(frames['T1_ema_sensitivity.csv'])==9 and len(frames['T2_donchian_sensitivity.csv'])==9
    assert len(frames['T3_tsmom_sensitivity.csv'])==3 and len(frames['stop_sensitivity.csv'])==9
    assert len(frames['cost_stress.csv'])==9
    summary=frames['W02_summary.csv']
    for _,s in summary.iterrows():
        a=frames['asset_contribution.csv'].query('strategy == @s.strategy')
        assert np.isclose(a.net_pnl.sum(),s.total_return*100000)
        cal=frames['calendar_metrics.csv'].query('strategy == @s.strategy')
        assert np.isclose((1+cal.return_pct).prod(),1+s.total_return)
    preservation=json.loads((ROOT/'W01_preservation.json').read_text())
    assert preservation['sha256']==frozen_files(), 'W01 preservation verification failed'
    diag=frames['trade_diagnostics.csv'].query("symbol=='ALL'")
    svg_chart('holding_distribution.svg','Holding bars: P10 / median / P90',
              [r.strategy+' '+q for _,r in diag.iterrows() for q in ['P10','P50','P90']],
              [r['holding_'+q.lower()] for _,r in diag.iterrows() for q in ['P10','P50','P90']])
    svg_chart('mfe_mae_realized.svg','Mean per-trade MFE / MAE / net realized return',
              [r.strategy+' '+q for _,r in diag.iterrows() for q in ['MFE','MAE','Realized']],
              [r[q] for _,r in diag.iterrows() for q in ['mfe_mean','mae_mean','realized_return_mean']],True)
    for path in (ROOT/'figures').glob('*.svg'): raster_preview(path)
    test=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],capture_output=True,text=True)
    (ROOT/'unit_tests.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
    assert test.returncode==0, 'Unit tests failed'
    (ROOT/'output_validation.json').write_text(json.dumps(dict(status='PASS',reproduction_checks=len(frames['baseline_reproduction.csv']),
                  signal_configurations=21,stop_configurations=9,cost_scenarios=9,
                  original_w01_unchanged=True,svg_count=len(list((ROOT/'figures').glob('*.svg'))),
                  png_count=len(list((ROOT/'figures').glob('*.png'))),
                  asset_reconciliation=True,calendar_compounding_reconciliation=True),indent=2))
    manifest=json.loads((ROOT/'manifest.json').read_text())
    paths=[p for p in ROOT.rglob('*') if p.is_file() and p.name!='manifest.json']
    paths+=list(Path('alpha_lab').glob('w02*.py'))+[Path('tests/test_w02.py'),Path('config/w02_diagnostic_sensitivity.yaml')]
    manifest['sha256']={str(p):sha(p) for p in paths}
    manifest['final_validation']='PASS'
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2))
    # New output bundle only. W01 dependencies remain read-only in the project.
    bundle=Path('W02_Diagnostic_Sensitivity_Cycle.zip')
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
        for p in paths+[ROOT/'manifest.json']:
            z.write(p,p.as_posix())
    print('FINAL_VALIDATION PASS; bundle bytes',bundle.stat().st_size,flush=True)

if __name__=='__main__': main()
