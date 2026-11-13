"""平台视频适配器：提交/轮询/下载、失败路径、任务幂等与接口鉴权。"""
import httpx
import respx
from sqlalchemy import select

from app import config
from app.db import SessionLocal
from app.models import AIJob, TaskExecution
from app.video_provider import VideoUnavailable, download, generate, submit, wait

API = 'https://pios.example.test/api/v1'


def _enable(monkeypatch):
    monkeypatch.setattr(config, 'PIOS_API_URL', API)
    monkeypatch.setattr(config, 'PIOS_TOKEN', 'test-only-token')
    monkeypatch.setattr(config, 'VIDEO_POLL_INTERVAL', 0.0)
    monkeypatch.setattr(config, 'VIDEO_TIMEOUT', 5.0)


@respx.mock
def test_submit_polls_and_downloads(monkeypatch, tmp_path):
    _enable(monkeypatch)
    # 平台真实形态是 {success, message, data} 信封，适配器需解包。
    respx.post(API + '/agent-api/video/generate').mock(return_value=httpx.Response(200, json={
        'success': True, 'data': {'task_id': 42, 'status': 'pending', 'model_used': 'MiniMax-H3'}}))
    respx.get(API + '/agent-api/video/tasks/42').mock(return_value=httpx.Response(200, json={
        'success': True, 'data': {'status': 'succeeded',
                                  'preview_url': '/api/v1/files/preview?object_name=video_gen/1.mp4',
                                  'duration_seconds': 5, 'credits_charged': 37.5,
                                  'object_key': 'video_gen/1.mp4'}}))
    respx.get('https://pios.example.test/api/v1/files/preview?object_name=video_gen/1.mp4').mock(
        return_value=httpx.Response(200, content=b'fake-mp4-bytes'))
    out = tmp_path / 'out.mp4'
    with SessionLocal() as db:
        result = generate(db, '一只猫在雨中奔跑', out_path=out)
        db.commit()
        job = db.scalars(select(AIJob).where(AIJob.kind == 'video')).one()
        assert job.status == 'succeeded' and job.provider == 'pios'
        assert 'test-only-token' not in str(job.output)
    assert out.read_bytes() == b'fake-mp4-bytes'
    assert result['task_id'] == 42 and result['credits_charged'] == 37.5
    sent = respx.calls[0].request
    assert sent.headers['authorization'] == 'Bearer test-only-token'


@respx.mock
def test_submit_falls_back_when_primary_upstream_unavailable(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(config, 'VIDEO_MODEL', 'MiniMax-H3')
    monkeypatch.setattr(config, 'VIDEO_RESOLUTION', '2K')
    monkeypatch.setattr(config, 'VIDEO_FALLBACK_MODEL', 'doubao-seedance-2-0-mini-260615')
    monkeypatch.setattr(config, 'VIDEO_FALLBACK_RESOLUTION', '720P')
    route = respx.post(API + '/agent-api/video/generate')
    route.side_effect = [
        httpx.Response(502, json={'error': {'type': 'upstream_error'}}),
        httpx.Response(200, json={'success': True, 'data': {
            'task_id': 5, 'status': 'pending',
            'model_used': 'doubao-seedance-2-0-mini-260615'}}),
    ]
    receipt = submit('竖版短视频')
    assert receipt['task_id'] == 5
    import json
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert bodies[0]['model'] == 'MiniMax-H3' and bodies[0]['resolution'] == '2K'
    assert bodies[1]['model'] == 'doubao-seedance-2-0-mini-260615'
    assert bodies[1]['resolution'] == '720P'


@respx.mock
def test_download_does_not_leak_token_to_cdn(monkeypatch, tmp_path):
    _enable(monkeypatch)
    route = respx.get('https://cdn.example.test/v/1.mp4').mock(
        return_value=httpx.Response(200, content=b'cdn-mp4'))
    out = tmp_path / 'cdn.mp4'
    download({'video_url': 'https://cdn.example.test/v/1.mp4'}, out)
    assert out.read_bytes() == b'cdn-mp4'
    assert 'authorization' not in route.calls[0].request.headers


@respx.mock
def test_failed_task_raises_and_records_audit(monkeypatch, tmp_path):
    _enable(monkeypatch)
    respx.post(API + '/agent-api/video/generate').mock(return_value=httpx.Response(200, json={
        'task_id': 7, 'status': 'pending'}))
    respx.get(API + '/agent-api/video/tasks/7').mock(return_value=httpx.Response(200, json={
        'status': 'failed', 'error': '上游拒绝'}))
    with SessionLocal() as db:
        try:
            generate(db, 'prompt', out_path=tmp_path / 'x.mp4')
            raise AssertionError('应当失败')
        except VideoUnavailable as exc:
            assert '上游拒绝' in str(exc)
        db.commit()
        job = db.scalars(select(AIJob).where(AIJob.kind == 'video')).one()
        assert job.status == 'failed' and '上游拒绝' not in job.error


@respx.mock
def test_queue_full_is_reported(monkeypatch):
    _enable(monkeypatch)
    respx.post(API + '/agent-api/video/generate').mock(return_value=httpx.Response(
        429, json={'retry_after_s': 30}))
    try:
        submit('prompt')
        raise AssertionError('应当失败')
    except VideoUnavailable as exc:
        assert '30' in str(exc)


def test_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(config, 'PIOS_API_URL', '')
    monkeypatch.setattr(config, 'PIOS_TOKEN', '')
    try:
        submit('prompt')
        raise AssertionError('应当失败')
    except VideoUnavailable as exc:
        assert '未配置' in str(exc)


@respx.mock
def test_wait_tolerates_transient_5xx(monkeypatch):
    _enable(monkeypatch)
    route = respx.get(API + '/agent-api/video/tasks/9')
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={
        'status': 'succeeded', 'video_url': 'https://cdn.example.test/a.mp4'})]
    data = wait(9)
    assert data['status'] == 'succeeded'


def test_video_endpoint_requires_config(client, headers):
    response = client.post('/api/v1/video/generate', json={'prompt': '测试'}, headers=headers)
    assert response.status_code == 503
    assert client.get('/api/v1/video/status', headers=headers).json()['configured'] is False


@respx.mock
def test_video_endpoint_runs_task(client, headers, monkeypatch, tmp_path):
    _enable(monkeypatch)
    monkeypatch.setattr(config, 'VIDEO_OUTPUT_DIR', tmp_path)
    respx.post(API + '/agent-api/video/generate').mock(return_value=httpx.Response(200, json={
        'task_id': 11, 'status': 'pending'}))
    respx.get(API + '/agent-api/video/tasks/11').mock(return_value=httpx.Response(200, json={
        'status': 'succeeded', 'video_url': 'https://cdn.example.test/b.mp4'}))
    respx.get('https://cdn.example.test/b.mp4').mock(return_value=httpx.Response(200, content=b'mp4'))
    response = client.post('/api/v1/video/generate', json={'prompt': '竖版短视频'}, headers=headers)
    assert response.status_code == 202, response.text
    tid = response.json()['task_id']
    task = client.get(f'/api/v1/video/tasks/{tid}', headers=headers).json()
    assert task['status'] == 'succeeded', task
    assert task['result']['task_id'] == 11
    # 同参数重复提交复用同一任务，不重复计费。
    again = client.post('/api/v1/video/generate', json={'prompt': '竖版短视频'}, headers=headers)
    assert again.json()['task_id'] == tid


def test_video_task_file_serves_only_output_dir(client, headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'VIDEO_OUTPUT_DIR', tmp_path)
    video = tmp_path / 'done.mp4'
    video.write_bytes(b'mp4-bytes')
    outside = tmp_path.parent / 'outside.mp4'
    outside.write_bytes(b'secret')
    with SessionLocal() as db:
        ok = TaskExecution(task_key='video:file-ok', kind='video_generate', status='succeeded',
                           payload={}, result={'path': str(video)})
        escape = TaskExecution(task_key='video:file-escape', kind='video_generate', status='succeeded',
                               payload={}, result={'path': str(outside)})
        pending = TaskExecution(task_key='video:file-pending', kind='video_generate', status='running',
                                payload={}, result={})
        db.add_all([ok, escape, pending])
        db.commit()
        ids = (ok.id, escape.id, pending.id)
    response = client.get(f'/api/v1/video/tasks/{ids[0]}/file', headers=headers)
    assert response.status_code == 200 and response.content == b'mp4-bytes'
    assert client.get(f'/api/v1/video/tasks/{ids[1]}/file', headers=headers).status_code == 404
    assert client.get(f'/api/v1/video/tasks/{ids[2]}/file', headers=headers).status_code == 404


def test_video_task_404_for_other_kind(client, headers):
    with SessionLocal() as db:
        job = TaskExecution(task_key='daily:x', kind='daily_generate', payload={})
        db.add(job)
        db.commit()
        tid = job.id
    assert client.get(f'/api/v1/video/tasks/{tid}', headers=headers).status_code == 404
