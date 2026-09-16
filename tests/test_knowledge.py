from app.services.indicator_master import resolve_candidates

def test_alias():
    assert resolve_candidates('RB库存')[0]['indicator_id'] == 'COMMODITY_REBAR_SOCIAL_INVENTORY'

def test_unknown():
    assert resolve_candidates('完全不存在的指标XYZ') == []
