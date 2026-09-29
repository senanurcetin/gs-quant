"""
Copyright 2026 Senanur Çetin.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import datetime as dt
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from gs_quant.timeseries.risk_metrics import VaRMethod

from . import analysis

STATIC_DIR = Path(__file__).parent / 'static'
MAX_BODY_BYTES = 1_000_000

# No inline script or style and no third party origin: the page needs nothing but its own files
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    'Content-Security-Policy': CONTENT_SECURITY_POLICY,
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
}


class AnalyzeRequest(BaseModel):
    """Either returns or prices must be given, not both"""

    model_config = ConfigDict(extra='forbid')

    returns: Optional[list[float]] = Field(None, max_length=analysis.MAX_OBSERVATIONS)
    prices: Optional[list[float]] = Field(None, max_length=analysis.MAX_OBSERVATIONS + 1)
    dates: Optional[list[dt.date]] = Field(None, max_length=analysis.MAX_OBSERVATIONS + 1)
    confidence: float = Field(0.95, ge=0.8, le=0.999)
    method: Literal['historical', 'parametric', 'cornish_fisher'] = 'historical'
    window: int = Field(250, ge=30, le=2000)
    minimum_acceptable_return: float = Field(0.0, ge=-0.5, le=0.5)
    periods_per_year: Optional[int] = Field(None, ge=1, le=366)

    @model_validator(mode='after')
    def _exactly_one_input(self):
        if (self.returns is None) == (self.prices is None):
            raise ValueError('Provide either returns or prices')
        return self


def _error(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({'error': message, **extra}, status_code=status)


def _validation_message(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = '.'.join(str(p) for p in item['loc'])
        parts.append(f'{where}: {item["msg"]}' if where else item['msg'])
    return '; '.join(parts)


async def index(request: Request) -> Response:
    return FileResponse(STATIC_DIR / 'index.html')


async def health(request: Request) -> Response:
    return JSONResponse({'status': 'ok'})


async def scenarios(request: Request) -> Response:
    return JSONResponse(
        [{'id': key, 'title': p['title'], 'description': p['description']} for key, p in analysis.SCENARIOS.items()]
    )


async def sample(request: Request) -> Response:
    scenario = request.query_params.get('scenario', 'volatile')
    try:
        n = int(request.query_params.get('n', 1000))
        seed = int(request.query_params.get('seed', 7))
        series = await run_in_threadpool(analysis.simulate_returns, scenario, n, seed)
    except ValueError as e:  # includes analysis.AnalysisError
        return _error(422, str(e))
    return JSONResponse(
        {
            'scenario': scenario,
            'dates': [str(d.date()) for d in series.index],
            'returns': [round(float(v), 6) for v in series],
        }
    )


async def analyze(request: Request) -> Response:
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return _error(413, f'Request body is larger than {MAX_BODY_BYTES} bytes')
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _error(413, f'Request body is larger than {MAX_BODY_BYTES} bytes')
    try:
        params = AnalyzeRequest.model_validate_json(body)
    except ValidationError as e:
        return _error(422, _validation_message(e))

    def run() -> dict:
        values, kind = (params.prices, 'prices') if params.prices is not None else (params.returns, 'returns')
        returns, assumptions = analysis.build_series(values, params.dates, kind)
        return analysis.analyze(
            returns,
            confidence=params.confidence,
            method=VaRMethod(params.method),
            window=params.window,
            minimum_acceptable_return=params.minimum_acceptable_return,
            periods_per_year=params.periods_per_year,
            assumptions=assumptions,
        )

    try:
        return JSONResponse(await run_in_threadpool(run))
    except analysis.AnalysisError as e:
        return _error(422, str(e))


class SecurityHeadersMiddleware:
    """Adds security headers to every response, and stops browsers caching API results"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        is_api = scope['path'].startswith('/api/')

        async def send_with_headers(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                present = {name.lower() for name, _ in headers}
                extra = dict(SECURITY_HEADERS)
                if is_api:
                    extra['Cache-Control'] = 'no-store'
                headers += [
                    (k.lower().encode(), v.encode()) for k, v in extra.items() if k.lower().encode() not in present
                ]
                message['headers'] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app() -> Starlette:
    routes = [
        Route('/', index),
        Route('/api/health', health),
        Route('/api/scenarios', scenarios),
        Route('/api/sample', sample),
        Route('/api/analyze', analyze, methods=['POST']),
        Mount('/static', StaticFiles(directory=STATIC_DIR), name='static'),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
