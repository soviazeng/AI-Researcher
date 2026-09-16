import json
from app.services.indicator_master import all_indicators, resolve_candidates
from app.services.prompts import SYSTEM_PROMPT
from app.services.llm import LLMService
from app.services.ocr import VisionOCR

class FinancialDataAgent:
    def __init__(self):
        self.llm = LLMService()
        self.vision = VisionOCR()

    def schema(self):
        change = {'type':['object','null'],'properties':{
            'type':{'type':['string','null']},'value':{'type':['number','null']},'unit':{'type':['string','null']}
        },'required':['type','value','unit'],'additionalProperties':False}
        candidate = {'type':'object','properties':{
            'indicator_id':{'type':'string'},'standard_name':{'type':'string'},'score':{'type':'number'}
        },'required':['indicator_id','standard_name','score'],'additionalProperties':False}
        record = {'type':'object','properties':{
            'raw_indicator':{'type':['string','null']},'indicator_id':{'type':['string','null']},
            'standard_indicator':{'type':['string','null']},'category':{'type':['string','null']},
            'date':{'type':['string','null']},'value':{'type':['number','null']},
            'original_value':{'type':['string','null']},'unit':{'type':['string','null']},
            'frequency':{'type':['string','null']},'change':change,
            'market':{'type':['string','null']},'region':{'type':['string','null']},
            'source':{'type':['string','null']},'evidence':{'type':['string','null']},
            'confidence':{'type':'number'},'status':{'type':'string','enum':['ready','pending_review']},
            'warnings':{'type':'array','items':{'type':'string'}},'candidates':{'type':'array','items':candidate}
        },'required':['raw_indicator','indicator_id','standard_indicator','category','date','value','original_value','unit','frequency','change','market','region','source','evidence','confidence','status','warnings','candidates'],'additionalProperties':False}
        return {'type':'object','properties':{
            'records':{'type':'array','items':record},'global_warnings':{'type':'array','items':{'type':'string'}}
        },'required':['records','global_warnings'],'additionalProperties':False}

    def prompt(self, context, text):
        knowledge = json.dumps(all_indicators(), ensure_ascii=False)
        return SYSTEM_PROMPT + f'''\n上下文：\n{context or '无'}\n\n指标知识库：\n{knowledge}\n\n输入：\n{text}'''

    def post_process(self, result, input_type, raw_text=None):
        known = {x['indicator_id'] for x in all_indicators()}
        for r in result['records']:
            candidates = resolve_candidates(r.get('raw_indicator'), 3)
            r['candidates'] = candidates
            if r.get('indicator_id') not in known:
                r['indicator_id'] = None; r['standard_indicator'] = None; r['category'] = None
            if r['indicator_id'] is None and candidates and candidates[0]['score'] >= 0.95:
                r['indicator_id'] = candidates[0]['indicator_id']; r['standard_indicator'] = candidates[0]['standard_name']
            if not r.get('date'):
                r['status'] = 'pending_review'; r['warnings'].append('缺少完整日期')
            if r.get('value') is None:
                r['status'] = 'pending_review'; r['warnings'].append('缺少数值')
            if not r.get('unit'):
                r['status'] = 'pending_review'; r['warnings'].append('缺少单位')
            if r.get('confidence',0) < 0.95:
                r['status'] = 'pending_review'
        result.update({'input_type':input_type,'raw_text':raw_text,'model':self.llm.model,'prompt_version':'v1.1'})
        return result

    def extract_text(self, text, context=''):
        if not self.llm.enabled():
            return {'input_type':'text','raw_text':text,'records':[],'global_warnings':['未设置 OPENAI_API_KEY'],'model':self.llm.model,'prompt_version':'v1.1'}
        result = self.llm.run(self.prompt(context,text), [{'type':'input_text','text':'请从上面的输入中提取全部金融数据并输出结构化记录。'}], self.schema())
        return self.post_process(result,'text',text)

    def extract_image(self, content, content_type, context=''):
        if not self.llm.enabled():
            return {'input_type':'image','records':[],'global_warnings':['未设置 OPENAI_API_KEY'],'model':self.llm.model,'prompt_version':'v1.1'}
        data_url = self.vision.to_data_url(content,content_type)
        result = self.llm.run(self.prompt(context,'图片是原始证据。直接读取图片中的文字、表格和金融数据，不要猜测模糊内容。'), [
            {'type':'input_text','text':'请从图片中提取全部金融数据，并输出结构化记录。'},
            {'type':'input_image','image_url':data_url,'detail':'high'}
        ], self.schema())
        return self.post_process(result,'image')
