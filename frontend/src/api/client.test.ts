import { makeHealth } from '../test/fixtures';
import { ApiError, fetchHealth } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(body: string, status: number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(new Response(body, { status }))),
  );
}

describe('fetchHealth', () => {
  it('returns the degraded body as-is on 200', async () => {
    stubFetch(JSON.stringify(makeHealth({ status: 'degraded', ingest_error: 'boom' })), 200);
    await expect(fetchHealth()).resolves.toMatchObject({
      status: 'degraded',
      ingest_error: 'boom',
    });
  });

  it('still reads a JSON health body sent with a 503', async () => {
    stubFetch(JSON.stringify(makeHealth({ status: 'degraded', ingest_error: 'boom' })), 503);
    await expect(fetchHealth()).resolves.toMatchObject({
      status: 'degraded',
      ingest_error: 'boom',
    });
  });

  it('never reports a 5xx as ok', async () => {
    stubFetch(JSON.stringify(makeHealth({ status: 'ok' })), 503);
    await expect(fetchHealth()).resolves.toMatchObject({ status: 'degraded' });
  });

  it('throws when the backend is unreachable or answers without a health body', async () => {
    stubFetch('Bad gateway', 502);
    await expect(fetchHealth()).rejects.toBeInstanceOf(ApiError);
  });
});
