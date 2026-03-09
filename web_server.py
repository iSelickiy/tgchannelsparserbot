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
    summary_id = int(request.match_info['id'])
    summary = get_summary(summary_id)
    if not summary:
        raise web.HTTPNotFound()

    html_content = md.markdown(
        summary['content'],
        extensions=['extra', 'nl2br']
    )
    return {'summary': summary, 'html_content': html_content}


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
