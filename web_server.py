import logging
import markdown as md
import aiohttp_jinja2
import jinja2
from aiohttp import web
from storage import get_summary, get_recent_summaries
from config import WEB_PORT

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.get('/')
@aiohttp_jinja2.template('index.html')
async def index(request):
    summaries = get_recent_summaries(30)
    return {'summaries': summaries}


@routes.get('/summary/{id}')
@aiohttp_jinja2.template('summary.html')
async def view_summary(request):
    try:
        summary_id = int(request.match_info['id'])
    except ValueError:
        raise web.HTTPBadRequest()
    summary = get_summary(summary_id)
    if not summary:
        raise web.HTTPNotFound()

    html_content = md.markdown(
        summary['content'],
        extensions=['extra', 'nl2br']
    )
    return {'summary': summary, 'html_content': html_content}


@routes.post('/api/ask')
async def ask_question(request):
    """API для чата по сводке: принимает summary_id и question, возвращает ответ."""
    from summarizer import ask_about_summary

    try:
        data = await request.json()
    except Exception:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    summary_id = data.get('summary_id')
    question = (data.get('question') or '').strip()

    if not summary_id or not question:
        return web.json_response({'error': 'summary_id and question required'}, status=400)

    if len(question) > 500:
        return web.json_response({'error': 'Question too long (max 500 chars)'}, status=400)

    summary = get_summary(int(summary_id))
    if not summary:
        return web.json_response({'error': 'Summary not found'}, status=404)

    try:
        answer = await ask_about_summary(summary['content'], question)
        answer_html = md.markdown(answer, extensions=['extra', 'nl2br'])
        return web.json_response({'answer': answer, 'answer_html': answer_html})
    except Exception as e:
        logger.exception("Error in /api/ask")
        return web.json_response({'error': str(e)}, status=500)


async def create_web_app():
    app = web.Application()
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('templates'))
    app.add_routes(routes)
    app.router.add_static('/static', 'static')
    return app


async def start_web_server():
    app = await create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEB_PORT)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {WEB_PORT}")
