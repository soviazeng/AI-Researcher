from difflib import SequenceMatcher

INDICATORS = [
 {'indicator_id':'COMMODITY_REBAR_SOCIAL_INVENTORY','standard_name':'螺纹钢社会库存','category':'商品/库存','aliases':['螺纹库存','螺纹社库','螺纹钢库存','螺纹社会库存','RB库存'],'default_unit':'万吨','frequency':'weekly'},
 {'indicator_id':'COMMODITY_REBAR_MILL_INVENTORY','standard_name':'螺纹钢厂库','category':'商品/库存','aliases':['螺纹厂库','螺纹钢厂库','钢厂螺纹库存'],'default_unit':'万吨','frequency':'weekly'},
 {'indicator_id':'COMMODITY_QHD_PORT_COAL_INVENTORY','standard_name':'秦皇岛港煤炭库存','category':'商品/库存','aliases':['秦港库存','秦皇岛港库存','秦港煤炭库存'],'default_unit':'万吨','frequency':'daily'},
 {'indicator_id':'COMMODITY_LITHIUM_CARBONATE_PRICE','standard_name':'碳酸锂价格','category':'商品/价格','aliases':['碳酸锂现货价','电池级碳酸锂价格','锂价','碳酸锂'],'default_unit':'元/吨','frequency':'daily'},
 {'indicator_id':'MACRO_CPI','standard_name':'居民消费价格指数','category':'宏观/价格','aliases':['CPI','居民消费价格','消费者价格指数'],'default_unit':'%','frequency':'monthly'},
 {'indicator_id':'MACRO_PPI','standard_name':'工业生产者出厂价格指数','category':'宏观/价格','aliases':['PPI','工业品出厂价格','工业生产者出厂价格'],'default_unit':'%','frequency':'monthly'}
]

def all_indicators():
    return INDICATORS

def resolve_candidates(raw_name, top_k=3):
    q = (raw_name or '').strip().lower()
    if not q:
        return []
    scored = []
    for item in INDICATORS:
        names = [item['standard_name'], *item['aliases']]
        score = max(SequenceMatcher(None, q, n.lower()).ratio() for n in names)
        if q == item['standard_name'].lower() or q in [a.lower() for a in item['aliases']]:
            score = 1.0
        elif any(a.lower() in q or q in a.lower() for a in item['aliases']):
            score = max(score, 0.88)
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{'indicator_id':i['indicator_id'],'standard_name':i['standard_name'],'score':round(s,4)} for s,i in scored[:top_k] if s >= 0.45]
