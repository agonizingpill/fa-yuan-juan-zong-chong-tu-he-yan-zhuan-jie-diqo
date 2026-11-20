import logging
from sqlalchemy import text
from .database import engine

# create_all 只建缺失的表，不会给既有表补列。演示环境沿用既有数据卷时，
# 这里按需补齐自带材料摘要与双侧推荐所需的列，并确保同版本唯一送审的索引存在。
COLUMNS={
    'intakes':[
        ('materials_summary',"TEXT NULL"),
        ('materials_version',"INT NOT NULL DEFAULT 0"),
    ],
    'triages':[
        ('materials_version',"INT NOT NULL DEFAULT 0"),
        ('materials_predicted',"VARCHAR(20) NULL"),
        ('materials_confidence',"FLOAT NULL"),
        ('source_conflict',"BOOL NOT NULL DEFAULT 0"),
        ('adopted_source',"VARCHAR(20) NULL"),
        ('adopt_reason',"VARCHAR(200) NOT NULL DEFAULT ''"),
    ],
}
VERSION_UNIQUE=('intake_id','facts_version','materials_version')

def _columns(conn,table):
    return {r[0] for r in conn.execute(text(
        'SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=:t'
    ),{'t':table})}

def _has_version_unique(conn):
    rows=conn.execute(text(
        "SELECT index_name,column_name FROM information_schema.statistics "
        "WHERE table_schema=DATABASE() AND table_name='triages' AND non_unique=0 "
        "ORDER BY index_name,seq_in_index"
    )).all()
    grouped={}
    for name,column in rows:grouped.setdefault(name,[]).append(column)
    return any(tuple(columns)==VERSION_UNIQUE for columns in grouped.values())

def sync():
    if engine.dialect.name!='mysql':return
    log=logging.getLogger('aid.schema')
    with engine.begin() as conn:
        for table,columns in COLUMNS.items():
            existing=_columns(conn,table)
            for name,ddl in columns:
                if name in existing:continue
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
                log.info('added column %s.%s',table,name)
    # 唯一索引单独提交；旧数据卷若已有重复记录则保留业务校验，不阻断启动
    try:
        with engine.begin() as conn:
            if _has_version_unique(conn):return
            conn.execute(text('ALTER TABLE triages ADD UNIQUE INDEX uq_triage_version (intake_id,facts_version,materials_version)'))
            log.info('added unique index uq_triage_version')
    except Exception:log.warning('unique index uq_triage_version 未建立（可能已有重复记录），去重改由业务校验保证',exc_info=True)
