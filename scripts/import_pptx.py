"""把两份公司介绍PPT的文本结构化导入 materials 表。
用法: python scripts/import_pptx.py ../拓客/*.pptx
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pptx import Presentation  # noqa: E402

from sqlalchemy import select
from app.db import SessionLocal  # noqa: E402
from app.models import Material  # noqa: E402


def slide_texts(path: str):
    p = Presentation(path)
    for i, s in enumerate(p.slides, 1):
        parts = []
        for sh in s.shapes:
            if sh.has_text_frame:
                t = re.sub(r"\s*\|\s*", "", sh.text_frame.text)
                if t.strip():
                    parts.append(t.strip())
            if sh.has_table:
                for row in sh.table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
        yield i, "\n".join(parts)


def guess_category(idx: int, text: str) -> tuple[str, str]:
    """返回 (category, publicity)"""
    if "明细表" in text or "签约代理" in text:
        return "产品明细", "public"
    if "简介" in text or "代理产品" in text:
        return "公司简介", "public"
    if "项目案例清单" in text or re.search(r"案例\s*\d", text):
        return "案例", "masked"   # 案例默认脱敏，由人工逐条确认可公开
    if "荣誉" in text or "资质" in text or "证书" in text:
        return "资质荣誉", "public"
    if "采购" in text or "商城" in text or "平台服务" in text:
        return "服务能力", "public"
    if "服务" in text or "系统集成" in text or "劳务派遣" in text:
        return "服务能力", "public"
    if "文化" in text or "理念" in text or "信条" in text or "团队" in text:
        return "企业文化", "public"
    if "历程" in text or "组织结构" in text:
        return "公司简介", "public"
    return "其他", "public"


def main():
    db = SessionLocal()
    n = 0
    for path in sys.argv[1:]:
        biz = "channel" if "渠道" in path else "project"
        for idx, text in slide_texts(path):
            if len(text.strip()) < 10:
                continue
            cat, pub = guess_category(idx, text)
            title = text.splitlines()[0][:80]
            source_tag = f"pptx:{Path(path).stem}:p{idx}"
            if db.scalar(select(Material).where(Material.tags == source_tag)):
                continue
            db.add(Material(category=cat, biz_line=biz, title=title,
                            content=text, publicity=pub, tags=source_tag))
            db.flush()
            n += 1
    db.commit()
    print(f"导入 {n} 条素材")
    db.close()


if __name__ == "__main__":
    main()
