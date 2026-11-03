import httpx
import respx
from datetime import date
from app import config
from app.db import SessionLocal
from app.llm import call_json
from app.models import AIJob
from sqlalchemy import select


@respx.mock
def test_ai_provider_failover_records_each_attempt(monkeypatch):
    monkeypatch.setattr(config, 'DEMO_MODE', False)
    monkeypatch.setattr(config, 'LLM_PROVIDERS', [
        {'name': 'bad', 'base_url': 'https://ai-bad.example.test/v1', 'key': 'test-only', 'model': 'test'},
        {'name': 'good', 'base_url': 'https://ai-good.example.test/v1', 'key': 'test-only', 'model': 'test'}])
    respx.post('https://ai-bad.example.test/v1/chat/completions').mock(return_value=httpx.Response(503))
    respx.post('https://ai-good.example.test/v1/chat/completions').mock(return_value=httpx.Response(200, json={
        'choices': [{'message': {'content': '{"score":82,"note":"ok"}'}}]}))
    with SessionLocal() as db:
        data = call_json(db, 'quality', 'system', 'input')
        db.commit()
        jobs = db.scalars(select(AIJob).order_by(AIJob.id)).all()
        assert data['score'] == 82
        assert [j.status for j in jobs] == ['failed', 'succeeded']
        assert [j.provider for j in jobs] == ['bad', 'good']
        assert all(j.duration_ms >= 0 and 'test-only' not in j.error for j in jobs)


@respx.mock
def test_http_ocr_real_protocol(image_bytes, monkeypatch):
    from app.ocr import recognize
    monkeypatch.setattr(config, 'OCR_BACKEND', 'http')
    monkeypatch.setattr(config, 'OCR_ENDPOINT', 'https://ocr.example.test/recognize')
    route = respx.post(config.OCR_ENDPOINT).mock(return_value=httpx.Response(200, json={
        'text': '播放123', 'fields': {'views': 123}, 'confidence': {'views': 0.94}}))
    raw, fields, confidence = recognize(image_bytes, 'metrics')
    assert raw == '播放123' and fields['views'] == 123 and confidence['views'] == 0.94
    assert 'multipart/form-data' in route.calls.last.request.headers['content-type']


def test_weekly_report_idempotency(client, headers):
    from app.report import make_weekly_report
    with SessionLocal() as db:
        first = make_weekly_report(db, date(2026, 10, 19))
        again = make_weekly_report(db, date(2026, 10, 19))
        assert first.id == again.id and first.report_md
    assert len(client.get('/api/v1/reports/weekly', headers=headers).json()) == 1
