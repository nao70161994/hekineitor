import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/api_client.js'), 'utf8');

describe('HekiApiClient', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.eval(source);
  });

  it('serializes JSON requests and returns the response payload', async () => {
    const response = new Response(
      JSON.stringify({status: 'ok'}),
      {status: 200, headers: {'Content-Type': 'application/json'}},
    );
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
    const payload = await window.HekiApiClient.requestJson('/api/test', {answer: 1});
    expect(payload).toEqual({status: 'ok'});
    expect(fetch).toHaveBeenCalledWith('/api/test', expect.objectContaining({method: 'POST'}));
  });

  it('turns HTTP 440 into a typed session-expired error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', {status: 440})));
    const promise = window.HekiApiClient.requestJson('/api/test', {});
    await expect(promise).rejects.toMatchObject({message: 'session_expired', status: 440});
  });

  it('surfaces a server-provided error message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({message: 'invalid request'}), {status: 400}),
      ),
    );
    await expect(
      window.HekiApiClient.requestJson('/api/test', {}),
    ).rejects.toMatchObject({message: 'invalid request', status: 400});
  });
});
