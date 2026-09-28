import { makeHealth } from '../test/fixtures';
import { monitoringStatus } from './health';

describe('monitoringStatus', () => {
  it('is unknown before /api/health answers', () => {
    expect(monitoringStatus(null)).toEqual({ kind: 'unknown' });
  });

  it('treats the older shape without ingest_error as healthy', () => {
    const health = makeHealth();
    expect('ingest_error' in health).toBe(false);
    expect(monitoringStatus(health)).toEqual({ kind: 'ok' });
  });

  it('is ok when the backend says ok and ingest_error is null', () => {
    expect(monitoringStatus(makeHealth({ status: 'ok', ingest_error: null }))).toEqual({
      kind: 'ok',
    });
  });

  it('is degraded with the error text while ingest is failing', () => {
    const health = makeHealth({
      status: 'degraded',
      ingest_error: "IsADirectoryError(21, 'Is a directory')",
    });
    expect(monitoringStatus(health)).toEqual({
      kind: 'degraded',
      error: "IsADirectoryError(21, 'Is a directory')",
    });
  });

  it('is degraded without an error message when only the status says so', () => {
    expect(monitoringStatus(makeHealth({ status: 'degraded', ingest_error: null }))).toEqual({
      kind: 'degraded',
      error: null,
    });
  });
});
