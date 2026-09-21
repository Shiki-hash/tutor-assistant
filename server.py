"""Loopback-only workbench. Credentials never leave the Python process."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from history import detail, summaries, checked_id
from uuid import uuid4
from app import ROOT, UserFacingError, generate, read_json, render_markdown, settings

TOKEN = secrets.token_urlsafe(32)
BUSY = threading.Lock()
STATUSES = ['待补充信息', '待老师核实', '待补充评价记录', '待状态排查', '待明确评价要求', '已解决']
TEACHER_RESULTS = ['尚未核查', '任课老师确认已掌握且已录入', '任课老师确认已掌握但未录入', '任课老师尚未确认掌握', '暂时查不到记录', '不适用']


def clean_string(data, key, maximum, required=False):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > maximum:
        raise UserFacingError(f'{key} 内容格式不正确或过长。')
    value = value.strip()
    if required and not value:
        raise UserFacingError('请填写学生问题。')
    return value


def make_case(data):
    case_id = data.get('case_id')
    samples = {x['id']: x for x in read_json(ROOT / 'cases.json')}
    if case_id not in samples:
        raise UserFacingError('请选择有效案例。')
    message = clean_string(data, 'message', 4000, True)
    context = clean_string(data, 'context', 4000)
    teacher = clean_string(data, 'teacher_result', 100)
    if teacher not in TEACHER_RESULTS:
        raise UserFacingError('请选择有效的老师核查结果。')
    original = samples[case_id]
    return dict(original, message=message, context=context, teacher_result=teacher,
                synthetic=message == original['message'] and context == original['context'] and teacher == original['teacher_result'])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def send(self, status, data, kind='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': '仅支持本机访问。'})
        path = urlparse(self.path).path
        if path in ('/api/history', '/api/issue'):
            if self.headers.get('X-Workbench-Token') != TOKEN:
                return self.send(403, {'error': '请刷新工作台后重试。'})
            try:
                if path == '/api/history':
                    return self.send(200, {'issues': summaries(ROOT / 'outputs')})
                identifier = parse_qs(urlparse(self.path).query).get('id', [''])[0]
                return self.send(200, detail(ROOT / 'outputs', identifier))
            except UserFacingError as exc:
                return self.send(400, {'error': str(exc)})
        if path == '/api/bootstrap':
            try:
                config = settings()
                ready, problem, model = True, '', config['TUTOR_MODEL'].removeprefix('openai/')
            except UserFacingError as exc:
                ready, problem, model = False, str(exc), '未配置'
            return self.send(200, {'token': TOKEN, 'cases': read_json(ROOT / 'cases.json'),
                                   'ready': ready, 'problem': problem, 'model': model,
                                   'teacher_results': TEACHER_RESULTS, 'statuses': STATUSES})
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path not in files:
            return self.send(404, {'error': '页面不存在。'})
        filename, kind = files[path]
        self.send(200, (ROOT / 'web' / filename).read_bytes(), kind)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Workbench-Token') != TOKEN:
            return self.send(403, {'error': '页面验证已失效，请刷新后再试。'})
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            return self.send(403, {'error': '不允许跨站请求。'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32000:
                return self.send(413, {'error': '输入过长，请缩短后重试。'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise UserFacingError('请求格式错误。')
            if self.path == '/api/generate':
                case = make_case(data)
                config = settings()
                if not BUSY.acquire(blocking=False):
                    return self.send(409, {'error': '已有生成任务运行中，请稍后再试。'})
                try:
                    parent = None
                    if data.get('issue_id'):
                        parent = detail(ROOT / 'outputs', data['issue_id'])
                        if data.get('revision') != parent['revision']:
                            return self.send(409, {'error': '这条问题已有新记录，请重新打开后继续。'})
                        latest = parent['versions'][-1]['record']['input']
                        if case['id'] != latest['id'] or case['message'] != latest['message']:
                            raise UserFacingError('继续处理不能更换原问题，请新建问题。')
                        followup = clean_string(data, 'followup', 2000, True)
                        case['context'] = latest['context'] + '\n\n后续补充：' + followup
                        if len(case['context']) > 12000:
                            raise UserFacingError('累计背景过长，请新建问题并整理必要背景。')
                        case['synthetic'] = parent['versions'][0]['record'].get('synthetic_input', True)
                    record = generate(case, read_json(ROOT / 'knowledge.json'), config)
                    run_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
                    record['issue_id'] = parent['issue_id'] if parent else run_id
                    if parent:
                        record['previous_run_id'] = parent['versions'][-1]['run_id']
                        record['followup'] = followup
                    directory = ROOT / 'outputs' / run_id
                    directory.mkdir(parents=True)
                    (directory / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                    (directory / 'reply.md').write_text(render_markdown(record), encoding='utf-8')
                    return self.send(200, {'run_id': run_id, 'record': record, 'revision': run_id + ':'})
                finally:
                    BUSY.release()
            if self.path == '/api/review':
                run_id = clean_string(data, 'run_id', 40)
                if not re.fullmatch(r'\d{8}-\d{6}-[0-9a-f]{8}', run_id):
                    raise UserFacingError('记录编号无效。')
                directory = ROOT / 'outputs' / run_id
                if not (directory / 'result.json').is_file():
                    raise UserFacingError('找不到原始生成记录，请重新生成。')
                reply = clean_string(data, 'reply', 4000, True)
                note = clean_string(data, 'note', 4000)
                status = clean_string(data, 'status', 30)
                if status not in STATUSES or data.get('reviewed') is not True:
                    raise UserFacingError('请核对回复、勾选确认，并选择有效状态。')
                if status == '已解决' and not note:
                    raise UserFacingError('标记已解决前，请填写解决依据。')
                review = dict(reply=reply, note=note, status=status, human_review='用户确认已核对',
                              saved_at=datetime.now(timezone.utc).isoformat())
                review_name = 'review-' + uuid4().hex[:8] + '.json'
                if not BUSY.acquire(blocking=False):
                    return self.send(409, {'error': '正在生成，请完成后再保存。'})
                try:
                    original = read_json(directory / 'result.json')
                    current = detail(ROOT / 'outputs', original.get('issue_id', run_id))
                    if current['versions'][-1]['run_id'] != run_id or (data.get('revision') and data['revision'] != current['revision']):
                        return self.send(409, {'error': '这条问题已有新记录，请重新打开后审核。'})
                    (directory / review_name).write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
                    return self.send(200, {'saved': True, 'file': f'outputs/{run_id}/{review_name}', 'revision': run_id + ':' + review_name})
                finally:
                    BUSY.release()
            return self.send(404, {'error': '接口不存在。'})
        except (UserFacingError, json.JSONDecodeError) as exc:
            return self.send(400, {'error': str(exc) if isinstance(exc, UserFacingError) else '请求格式错误。'})
        except Exception as exc:
            body = getattr(exc, 'body', {}) or {}
            error = body.get('error', body) if isinstance(body, dict) else {}
            code = error.get('code') if isinstance(error, dict) else None
            if code in ('credit_balance_exhausted', 'insufficient_quota') or getattr(exc, 'status_code', 0) == 402:
                message = '模型账户额度不足，请补充 API 额度后重试。'
            elif getattr(exc, 'status_code', 0) == 401:
                message = '模型密钥无效，请检查本机 .env 中的对应密钥。'
            elif 'Timeout' in type(exc).__name__:
                message = '生成超时，请稍后重试。上一次回复仍保留。'
            else:
                message = '生成或保存失败，请检查模型服务、网络及本机配置后重试。'
            return self.send(502, {'error': message})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Workbench: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()
