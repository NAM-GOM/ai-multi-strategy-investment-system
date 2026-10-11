import pandas as pd
import pytest
from trading_system.research.mr_w01.strategies import REGISTRY, RSIReversion, BollingerReversion, ShockReversal
from trading_system.research.mr_w01 import data
from test_mr_w01 import frame, orders, simulate

@pytest.mark.parametrize('prev,now,expected', [(29,30,True),(30,31,False),(29,29.9,False)])
def test_original_P01_rsi_cross_boundary(prev,now,expected):
    d=pd.DataFrame({'close':[100,101],'ema200':[90,90],'rsi14':[prev,now]})
    assert bool(RSIReversion()._generate_signals(d)[0].iloc[-1]) == expected

@pytest.mark.parametrize('prev,expected', [(89,True),(90,False),(91,False)])
def test_original_P02_band_return_boundary(prev,expected):
    d=pd.DataFrame({'close':[prev,90],'lower_band':[90,90],'ema200':[80,80],'sma20':[95,95]})
    assert bool(BollingerReversion()._generate_signals(d)[0].iloc[-1]) == expected

@pytest.mark.parametrize('recovery,expected',[(100,False),(100.1,True)])
def test_original_P03_shock_strict_recovery(recovery,expected):
    d=pd.DataFrame({'close':[100,recovery],'ema200':[90,90],'sma20':[105,105],'r3':[-.1,0],'r3_std60':[.05,.5]})
    assert bool(ShockReversal()._generate_signals(d)[0].iloc[-1]) == expected

@pytest.mark.parametrize('key',list(REGISTRY))
def test_original_P04_future_mutation(key):
    d=frame(); a=REGISTRY[key].generate(d)
    d.iloc[300:,d.columns.get_indexer(['open','high','low','close'])] *= 2
    b=REGISTRY[key].generate(d)
    pd.testing.assert_frame_equal(a.iloc[:300],b.iloc[:300],check_exact=True)

def test_original_P10_hash_tamper_fails(monkeypatch):
    monkeypatch.setattr(data,'sha256',lambda p:'0'*64)
    with pytest.raises(ValueError,match='hash mismatch'):
        data.load_snapshot()
