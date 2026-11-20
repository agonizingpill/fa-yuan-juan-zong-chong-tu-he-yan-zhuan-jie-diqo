import logging,time,json
from pathlib import Path
from .database import Session
from .models import Triage,Intake
from .common import get
from .triage_service import queue
from .algorithm import classify
logging.basicConfig(level=logging.INFO)
def stale(case,row):
    return case.facts_version!=row.facts_version or case.materials_version!=row.materials_version
def handle(db,row_id):
    row=db.get(Triage,row_id)
    if not row or row.status!='queued':return
    row.status='running';db.commit()
    try:
        case=db.get(Intake,row.intake_id)
        if stale(case,row):raise ValueError('事实或自带材料摘要已更新，请重新提交')
        facts_label,facts_confidence,metrics=classify(case.facts)
        row.predicted,row.confidence,row.metrics=facts_label,facts_confidence,metrics
        row.materials_predicted=row.materials_confidence=None
        summary=(case.materials_summary or '').strip()
        if summary:
            material_label,material_confidence,_=classify(summary)
            row.materials_predicted,row.materials_confidence=material_label,material_confidence
        row.source_conflict=bool(summary) and row.materials_predicted!=row.predicted
        row.manual_required=row.confidence<.68 or (row.materials_confidence is not None and row.materials_confidence<.68) or row.source_conflict
        # 锁住卷宗根再比对版本，确保与摘要/事实更正的提交串行；旧结果算完也不送审
        case=get(db,Intake,row.intake_id,True)
        if stale(case,row):
            row.status='stale';row.error='计算期间事实或材料摘要已更新，旧结果不送审'
        else:
            row.status='done'
        try:
            Path('/artifacts').mkdir(exist_ok=True);Path(f'/artifacts/triage-{row.id}.json').write_text(json.dumps({'facts':metrics,'materials':{'label':row.materials_predicted,'confidence':row.materials_confidence} if summary else None,'source_conflict':row.source_conflict},ensure_ascii=False))
        except OSError:logging.warning('artifact write failed for triage %s',row.id)
    except Exception as e:row.status='failed';row.error=str(e)[:200]
    db.commit()
def main():
    while True:
        Path('/tmp/worker-heartbeat').touch()
        try:
            item=queue.blpop('aid:triage',timeout=2)
            if not item:continue
            with Session() as db:handle(db,int(item[1]))
        except Exception:logging.exception('triage loop');time.sleep(1)
if __name__=='__main__':main()
