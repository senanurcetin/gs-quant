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
import hmac
import logging
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from gs_quant.timeseries.risk_metrics import VaRMethod

from . import analysis, marketdata, portfolio, report
from .settings import Settings
from .store import RunStore, StoreFull

logger = logging.getLogger('gs_quant.apps.risk_dashboard')

STATIC_DIR = Path(__file__).parent / 'static'
MAX_BODY_BYTES = Settings().max_body_bytes
MAX_NAME_LENGTH = 120
MIN_COMPARE, MAX_COMPARE = 2, 4
PUBLIC_API_PATHS = ('/api/health', '/api/ready')
REQUEST_ID = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
RUN_ID = re.compile(r'^[0-9a-f]{32}$')

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


class Scenario(BaseModel):
    """A what-if: how much each asset moves at once, as a fraction (-0.1 is a fall of 10%). An asset left out stays put."""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(..., min_length=1, max_length=60)
    shocks: dict[str, float] = Field(..., max_length=portfolio.MAX_ASSETS)

    @field_validator('name')
    @classmethod
    def _printable(cls, name: str) -> str:
        name = name.strip()
        if not name or not name.isprintable():
            raise ValueError('The name must be printable text')
        return name

    @field_validator('shocks')
    @classmethod
    def _plausible(cls, shocks: dict[str, float]) -> dict[str, float]:
        for asset, shock in shocks.items():
            if not -1 <= shock <= 10:  # a fall of more than 100% is impossible, a rise of 1,000% is not a scenario
                raise ValueError(f'The shock of {asset[:40]} must be between -100% and +1000%')
        return shocks


class _Settings(BaseModel):
    """The model settings shared by every kind of request"""

    model_config = ConfigDict(extra='forbid')

    confidence: float = Field(0.95, ge=0.8, le=0.999)
    method: Literal['historical', 'parametric', 'cornish_fisher'] = 'historical'
    window: int = Field(250, ge=30, le=2000)
    minimum_acceptable_return: float = Field(0.0, ge=-0.5, le=0.5)
    periods_per_year: Optional[int] = Field(None, ge=1, le=366)
    scenarios: list[Scenario] = Field(default_factory=list, max_length=analysis.MAX_SCENARIOS)


class AnalyzeRequest(_Settings):
    """Either returns or prices must be given, not both"""

    returns: Optional[list[float]] = Field(None, max_length=analysis.MAX_OBSERVATIONS)
    prices: Optional[list[float]] = Field(None, max_length=analysis.MAX_OBSERVATIONS + 1)
    dates: Optional[list[dt.date]] = Field(None, max_length=analysis.MAX_OBSERVATIONS + 1)

    @model_validator(mode='after')
    def _exactly_one_input(self):
        if (self.returns is None) == (self.prices is None):
            raise ValueError('Provide either returns or prices')
        return self


class PortfolioRequest(_Settings):
    """Returns or prices of several assets, by name, and their weights (equal weights when omitted)"""

    assets: dict[str, list[float]] = Field(..., max_length=portfolio.MAX_ASSETS)
    kind: Literal['returns', 'prices'] = 'returns'
    weights: Optional[dict[str, float]] = Field(None, max_length=portfolio.MAX_ASSETS)
    dates: Optional[list[dt.date]] = Field(None, max_length=analysis.MAX_OBSERVATIONS + 1)

    @field_validator('assets')
    @classmethod
    def _bounded_assets(cls, assets):
        if any(len(v) > analysis.MAX_OBSERVATIONS + 1 for v in assets.values()):
            raise ValueError(f'At most {analysis.MAX_OBSERVATIONS} observations per asset')
        return assets


class RunRequest(BaseModel):
    """A request to analyse and save"""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    kind: Literal['single', 'portfolio']
    request: dict[str, Any]

    @field_validator('name')
    @classmethod
    def _printable(cls, name: str) -> str:
        name = name.strip()
        if not name or not name.isprintable():
            raise ValueError('The name must be printable text')
        return name


REQUEST_MODELS = {'single': AnalyzeRequest, 'portfolio': PortfolioRequest}

HISTORY_YEARS = (1, 3, 5, 10)  # what the page offers besides "all"


class PortfolioBookRequest(BaseModel):
    """A portfolio to keep under a name: which symbols, at which weights, in which currency, over how much history"""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    symbols: list[str] = Field(..., min_length=2, max_length=marketdata.MAX_SYMBOLS)
    weights: dict[str, float] = Field(..., max_length=marketdata.MAX_SYMBOLS)
    base: Optional[str] = None
    years: Optional[int] = None

    @field_validator('name')
    @classmethod
    def _printable(cls, name: str) -> str:
        name = name.strip()
        if not name or not name.isprintable():
            raise ValueError('The name must be printable text')
        return name

    @field_validator('symbols')
    @classmethod
    def _valid_symbols(cls, symbols: list[str]) -> list[str]:
        cleaned = [s.strip().upper() for s in symbols]
        for symbol in cleaned:
            if not marketdata.SYMBOL.match(symbol):
                raise ValueError(f'"{symbol[:20]}" is not a valid symbol')
        if len(set(cleaned)) != len(cleaned):
            raise ValueError('Each symbol can be given once')
        return cleaned

    @field_validator('base')
    @classmethod
    def _currency(cls, base: Optional[str]) -> Optional[str]:
        try:
            return marketdata.parse_currency(base)
        except marketdata.MarketDataError as e:
            raise ValueError(str(e)) from e

    @field_validator('years')
    @classmethod
    def _history(cls, years: Optional[int]) -> Optional[int]:
        if years is not None and years not in HISTORY_YEARS:
            raise ValueError(f'The history must be one of {", ".join(map(str, HISTORY_YEARS))} years, or all of it')
        return years

    @model_validator(mode='after')
    def _weights_match_the_symbols(self):
        weights = {k.strip().upper(): v for k, v in self.weights.items()}
        if set(weights) != set(self.symbols) or len(weights) != len(self.weights):
            raise ValueError('Weights must be given for exactly the symbols, no more and no fewer')
        if not all(math.isfinite(v) for v in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError('Weights must be finite and add up to a positive number')
        self.weights = weights
        return self


def execute(kind: str, params: _Settings) -> dict:
    """Run the analysis for a validated request"""
    if kind == 'single':
        values, source = (params.prices, 'prices') if params.prices is not None else (params.returns, 'returns')
        returns, assumptions = analysis.build_series(values, params.dates, source)
        result = analysis.analyze(
            returns,
            confidence=params.confidence,
            method=VaRMethod(params.method),
            window=params.window,
            minimum_acceptable_return=params.minimum_acceptable_return,
            periods_per_year=params.periods_per_year,
            assumptions=assumptions,
        )
        weights = {analysis.SERIES_KEY: 1.0}
    else:
        result = portfolio.analyze_portfolio(
            params.assets,
            params.weights,
            params.dates,
            params.kind,
            confidence=params.confidence,
            method=VaRMethod(params.method),
            window=params.window,
            minimum_acceptable_return=params.minimum_acceptable_return,
            periods_per_year=params.periods_per_year,
        )
        weights = {asset['name']: asset['weight'] for asset in result['portfolio']['assets']}
    if params.scenarios:
        risk = analysis.headline(result)
        scenarios = [(s.name, {asset.strip(): shock for asset, shock in s.shocks.items()}) for s in params.scenarios]
        result['scenarios'] = analysis.what_if(scenarios, weights, risk['var'], risk['expected_shortfall'])
    return result


def _error(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({'error': message, **extra}, status_code=status)


def _validation_message(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = '.'.join(str(p) for p in item['loc'])
        parts.append(f'{where}: {item["msg"]}' if where else item['msg'])
    return '; '.join(parts)


class BodyTooLarge(Exception):
    pass


async def read_body(request: Request, limit: int) -> bytes:
    """The request body, refusing to buffer more than the limit (the declared length is not trusted)"""
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > limit:
        raise BodyTooLarge
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise BodyTooLarge
        chunks.append(chunk)
    return b''.join(chunks)


class Application:
    """The routes of the application, sharing its settings and the store of saved runs"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._store: Optional[RunStore] = None
        self.market: Optional[marketdata.MarketData] = marketdata.make_market_data(settings.market_data)

    @property
    def store(self) -> RunStore:
        # opened on first use, so that an app that never saves a run creates no file
        if self._store is None:
            self._store = RunStore(self.settings.database, self.settings.max_runs, self.settings.max_portfolios)
        return self._store

    async def _json(self, request: Request, model: type[BaseModel]):
        """The validated body, or the error response to return"""
        try:
            body = await read_body(request, self.settings.max_body_bytes)
        except BodyTooLarge:
            return _error(413, f'Request body is larger than {self.settings.max_body_bytes} bytes')
        try:
            return model.model_validate_json(body)
        except ValidationError as e:
            return _error(422, _validation_message(e))

    # ---- pages and probes

    async def index(self, request: Request) -> Response:
        return FileResponse(STATIC_DIR / 'index.html')

    async def health(self, request: Request) -> Response:
        from gs_quant import __version__

        return JSONResponse({'status': 'ok', 'version': str(__version__)})

    async def ready(self, request: Request) -> Response:
        try:
            await run_in_threadpool(self.store.ping)
        except Exception:
            logger.exception('Readiness check failed')
            return _error(503, 'The run store is not available')
        return JSONResponse({'status': 'ready'})

    async def config(self, request: Request) -> Response:
        """What the page needs to know to present itself"""
        return JSONResponse(
            {
                'auth_required': self.settings.api_token is not None,
                'market_data': self.market.label if self.market else None,
                'limits': {
                    'observations': analysis.MAX_OBSERVATIONS,
                    'assets': portfolio.MAX_ASSETS,
                    'body_bytes': self.settings.max_body_bytes,
                },
            }
        )

    # ---- analysis

    async def scenarios(self, request: Request) -> Response:
        return JSONResponse(
            [{'id': key, 'title': p['title'], 'description': p['description']} for key, p in analysis.SCENARIOS.items()]
        )

    async def sample(self, request: Request) -> Response:
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

    async def market_prices(self, request: Request) -> Response:
        """Daily closing prices by symbol, from the provider the server was configured with"""
        if self.market is None:
            return _error(404, 'Loading prices by symbol is not enabled on this server')
        params = request.query_params
        try:
            symbols = marketdata.parse_symbols(params.get('symbols', ''))
            start, end = (dt.date.fromisoformat(params[k]) if params.get(k) else None for k in ('start', 'end'))
        except marketdata.MarketDataError as e:
            return _error(e.status, str(e))
        except ValueError:
            return _error(422, 'Dates must be YYYY-MM-DD')
        try:
            return JSONResponse(await run_in_threadpool(self.market.prices, symbols, start, end, params.get('base')))
        except marketdata.MarketDataError as e:
            logger.warning('Market data request failed: %s', e)
            return _error(e.status, str(e))

    async def _analyse(self, request: Request, kind: str) -> Response:
        params = await self._json(request, REQUEST_MODELS[kind])
        if isinstance(params, Response):
            return params
        try:
            return JSONResponse(await run_in_threadpool(execute, kind, params))
        except analysis.AnalysisError as e:
            return _error(422, str(e))

    async def analyze(self, request: Request) -> Response:
        return await self._analyse(request, 'single')

    async def analyze_portfolio(self, request: Request) -> Response:
        return await self._analyse(request, 'portfolio')

    # ---- saved runs

    async def list_runs(self, request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(self.store.list))

    async def create_run(self, request: Request) -> Response:
        run = await self._json(request, RunRequest)
        if isinstance(run, Response):
            return run
        try:
            params = REQUEST_MODELS[run.kind].model_validate(run.request)
        except ValidationError as e:
            return _error(422, _validation_message(e))
        try:
            result = await run_in_threadpool(execute, run.kind, params)
        except analysis.AnalysisError as e:
            return _error(422, str(e))
        saved = await run_in_threadpool(
            self.store.add, run.name, run.kind, params.model_dump(mode='json'), analysis.headline(result)
        )
        logger.info('Saved run %s (%s)', saved['id'], run.kind)
        return JSONResponse(saved, status_code=201)

    async def _stored(self, request: Request):
        """The stored run named in the URL, or the error response to return"""
        run_id = request.path_params['run_id']
        stored = await run_in_threadpool(self.store.get, run_id) if RUN_ID.match(run_id) else None
        return stored if stored is not None else _error(404, 'There is no such run')

    async def _recompute(self, stored: dict) -> dict:
        params = REQUEST_MODELS[stored['kind']].model_validate(stored['request'])
        return await run_in_threadpool(execute, stored['kind'], params)

    async def get_run(self, request: Request) -> Response:
        stored = await self._stored(request)
        if isinstance(stored, Response):
            return stored
        try:
            result = await self._recompute(stored)
        except analysis.AnalysisError as e:  # the model code changed since the run was saved
            return _error(409, f'The saved run can no longer be analysed: {e}')
        meta = {k: stored[k] for k in ('id', 'name', 'kind', 'created_at', 'headline')}
        return JSONResponse({'run': meta, 'request': stored['request'], 'result': result})

    async def compare_runs(self, request: Request) -> Response:
        """The comparison figures of two to four saved runs, in the order asked for"""
        ids = [i for i in request.query_params.get('ids', '').split(',') if i]
        if not MIN_COMPARE <= len(ids) <= MAX_COMPARE or len(set(ids)) != len(ids):
            return _error(422, f'Choose between {MIN_COMPARE} and {MAX_COMPARE} different saved analyses to compare')
        if not all(RUN_ID.match(i) for i in ids):
            return _error(404, 'There is no such run')
        compared = []
        for run_id in ids:
            stored = await run_in_threadpool(self.store.get, run_id)
            if stored is None:
                return _error(404, 'There is no such run')
            try:
                result = await self._recompute(stored)
            except analysis.AnalysisError as e:
                return _error(409, f'The saved run "{stored["name"]}" can no longer be analysed: {e}')
            meta = {k: stored[k] for k in ('id', 'name', 'kind', 'created_at')}
            compared.append({**meta, 'metrics': analysis.comparison_metrics(result)})
        return JSONResponse({'runs': compared})

    # ---- named portfolios

    async def list_portfolios(self, request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(self.store.list_portfolios))

    async def save_portfolio(self, request: Request) -> Response:
        body = await self._json(request, PortfolioBookRequest)
        if isinstance(body, Response):
            return body
        definition = {
            'symbols': body.symbols,
            'weights': {s: body.weights[s] for s in body.symbols},
            'base': body.base,
            'years': body.years,
        }
        try:
            meta, created = await run_in_threadpool(self.store.save_portfolio, body.name, definition)
        except StoreFull as e:
            return _error(409, str(e))
        logger.info('%s portfolio %s', 'Saved' if created else 'Updated', meta['id'])
        return JSONResponse(meta, status_code=201 if created else 200)

    async def get_portfolio(self, request: Request) -> Response:
        portfolio_id = request.path_params['portfolio_id']
        found = await run_in_threadpool(self.store.get_portfolio, portfolio_id) if RUN_ID.match(portfolio_id) else None
        return JSONResponse(found) if found is not None else _error(404, 'There is no such portfolio')

    async def delete_portfolio(self, request: Request) -> Response:
        portfolio_id = request.path_params['portfolio_id']
        deleted = RUN_ID.match(portfolio_id) and await run_in_threadpool(self.store.delete_portfolio, portfolio_id)
        return Response(status_code=204) if deleted else _error(404, 'There is no such portfolio')

    async def delete_run(self, request: Request) -> Response:
        run_id = request.path_params['run_id']
        deleted = RUN_ID.match(run_id) and await run_in_threadpool(self.store.delete, run_id)
        return Response(status_code=204) if deleted else _error(404, 'There is no such run')

    async def run_report(self, request: Request) -> Response:
        stored = await self._stored(request)
        if isinstance(stored, Response):
            return stored
        try:
            result = await self._recompute(stored)
        except analysis.AnalysisError as e:
            return _error(409, f'The saved run can no longer be analysed: {e}')
        html = await run_in_threadpool(report.render_run, stored, result)
        return Response(
            html,
            media_type='text/html; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename="risk_report_{stored["id"][:8]}.html"',
                'Content-Security-Policy': report.content_security_policy(html),
            },
        )


class ApiGuardMiddleware:
    """Request ids, an access log, security headers and the optional bearer token

    The token is checked for every /api/ path but the probes. The page and its static files are public: they hold no data.
    """

    def __init__(self, app, api_token: Optional[str] = None):
        self.app = app
        self.api_token = api_token

    def _authorised(self, scope) -> bool:
        if self.api_token is None:
            return True
        for name, value in scope['headers']:
            if name == b'authorization':
                scheme, _, supplied = value.decode('latin-1').partition(' ')
                return scheme.lower() == 'bearer' and hmac.compare_digest(supplied.strip(), self.api_token)
        return False

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        path = scope['path']
        is_api = path.startswith('/api/')
        incoming = next((v.decode('latin-1') for k, v in scope['headers'] if k == b'x-request-id'), '')
        request_id = incoming if REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        scope.setdefault('state', {})['request_id'] = request_id
        status = 500
        started_response = False

        async def send_with_headers(message):
            nonlocal status, started_response
            if message['type'] == 'http.response.start':
                status = message['status']
                started_response = True
                headers = list(message.get('headers', []))
                present = {name.lower() for name, _ in headers}
                extra = {**SECURITY_HEADERS, 'X-Request-ID': request_id}
                if is_api:
                    extra['Cache-Control'] = 'no-store'
                headers += [
                    (k.lower().encode(), v.encode()) for k, v in extra.items() if k.lower().encode() not in present
                ]
                message['headers'] = headers
            await send(message)

        try:
            if is_api and path not in PUBLIC_API_PATHS and not self._authorised(scope):
                response = JSONResponse(
                    {'error': 'A valid access token is required'},
                    status_code=401,
                    headers={'WWW-Authenticate': 'Bearer'},
                )
                await response(scope, receive, send_with_headers)
            else:
                await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception('Unhandled error rid=%s', request_id)
            if not started_response:
                failure = _error(500, 'Something went wrong on the server', request_id=request_id)
                await failure(scope, receive, send_with_headers)
        finally:
            logger.info(
                '%s %s %s %.0fms rid=%s',
                scope['method'],
                path,
                status,
                (time.perf_counter() - started) * 1000,
                request_id,
            )


def create_app(settings: Optional[Settings] = None) -> Starlette:
    settings = settings or Settings()
    handlers = Application(settings)
    routes = [
        Route('/', handlers.index),
        Route('/api/health', handlers.health),
        Route('/api/ready', handlers.ready),
        Route('/api/config', handlers.config),
        Route('/api/scenarios', handlers.scenarios),
        Route('/api/sample', handlers.sample),
        Route('/api/market/prices', handlers.market_prices),
        Route('/api/analyze', handlers.analyze, methods=['POST']),
        Route('/api/portfolio', handlers.analyze_portfolio, methods=['POST']),
        Route('/api/portfolios', handlers.list_portfolios, methods=['GET']),
        Route('/api/portfolios', handlers.save_portfolio, methods=['POST']),
        Route('/api/portfolios/{portfolio_id}', handlers.get_portfolio, methods=['GET']),
        Route('/api/portfolios/{portfolio_id}', handlers.delete_portfolio, methods=['DELETE']),
        Route('/api/runs', handlers.list_runs, methods=['GET']),
        Route('/api/runs', handlers.create_run, methods=['POST']),
        Route('/api/runs/compare', handlers.compare_runs, methods=['GET']),
        Route('/api/runs/{run_id}', handlers.get_run, methods=['GET']),
        Route('/api/runs/{run_id}', handlers.delete_run, methods=['DELETE']),
        Route('/api/runs/{run_id}/report', handlers.run_report, methods=['GET']),
        Mount('/static', StaticFiles(directory=STATIC_DIR), name='static'),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(ApiGuardMiddleware, api_token=settings.api_token)
    app.state.application = handlers
    return app
