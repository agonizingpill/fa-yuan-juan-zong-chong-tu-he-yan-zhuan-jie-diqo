import os,redis
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import Intake,Triage,Audit
from .common import get,reject,finish,editable,dump
from .intake_service import authorized
queue=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)
def latest(db,id):
    case=get(db,Intake,id)
    return db.scalar(select(Triage).where(Triage.intake_id==id,Triage.facts_version==case.facts_version,Triage.materials_version==case.materials_version,Triage.status=='reviewed').order_by(Triage.id.desc()))
def same_version(db,id):
    case=get(db,Intake,id)
    return db.scalar(select(Triage).where(Triage.intake_id==id,Triage.facts_version==case.facts_version,Triage.materials_version==case.materials_version).order_by(Triage.id.desc()))
def enqueue(db,data,user):
    case=editable(db,data.intake_id);reject(not authorized(db,case.id),'未取得授权，不能提交行政分流')
    existing=same_version(db,case.id)
    if existing:
        if existing.status!='failed':
            # 同一版事实与材料摘要重试不重复送审，直接返回已有记录
            return {**dump(existing),'deduplicated':True}
        existing.status='queued';existing.error='';db.add(Audit(actor=user.username,action='分流失败重新排队',detail=str(existing.id)));db.commit();row=existing
    else:
        row=Triage(intake_id=case.id,facts_version=case.facts_version,materials_version=case.materials_version);db.add(row)
        try:
            db.flush();finish(db,user,'提交主题分流',row)
        except IntegrityError:
            # 并发提交同一版本时由唯一约束兜底，只保留一条送审记录
            db.rollback();existing=same_version(db,case.id)
            if not existing:raise
            return {**dump(existing),'deduplicated':True}
    try:queue.rpush('aid:triage',row.id)
    except redis.RedisError:
        row.status='failed';row.error='任务队列暂不可用，恢复后可重新提交';db.commit()
        raise HTTPException(503,row.error)
    return dump(row)
def review(db,id,data,user):
    initial=get(db,Triage,id);case=get(db,Intake,initial.intake_id,True);row=get(db,Triage,id,True)
    reject(row.status!='done','等待分流完成再复核')
    reject(row.facts_version!=case.facts_version or row.materials_version!=case.materials_version,'事实或自带材料摘要已更新，旧建议不能定题，请按新版重新分流')
    reject(not authorized(db,case.id),'来访授权已撤回')
    source=data.adopted_source
    if row.source_conflict:
        reject(source not in ('facts','materials','manual'),'事实与自带材料摘要指向不同主题，须写明采信哪一边及理由')
        reject(len((data.adopt_reason or '').strip())<3,'两边主题不同，采信理由至少3个字')
        if source!='manual':
            expected=row.predicted if source=='facts' else row.materials_predicted
            reject(data.topic!=expected,'采信'+('事实' if source=='facts' else '材料摘要')+'时，定题须与该边推荐主题一致；如需改判请选择人工改判')
    else:
        reject(source not in (None,'','facts','materials','both','manual'),'采信来源取值无效')
        source=source or ('both' if row.materials_predicted else 'facts')
    row.approved=data.topic;row.review_note=data.note;row.adopted_source=source;row.adopt_reason=(data.adopt_reason or '').strip();row.status='reviewed';return finish(db,user,'专长人工复核',row)
