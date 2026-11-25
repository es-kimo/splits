/**
 * court.splits.kr 앞단.
 *
 * - /api/* 는 오라클 인스턴스의 백엔드로 넘긴다. 브라우저에서 보면 같은 출처라 CORS 설정이 필요 없다.
 * - 나머지는 빌드된 정적 파일을 내려준다. 없는 경로는 wrangler 설정에 따라 index.html이 나간다.
 */

interface Env {
  ASSETS: Fetcher
  /** 예: https://court-api.splits.kr */
  API_ORIGIN: string
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url)

    if (url.pathname.startsWith('/api/')) {
      const target = new URL(url.pathname + url.search, env.API_ORIGIN)
      const headers = new Headers(request.headers)
      headers.set('X-Forwarded-Host', url.host)
      headers.set('X-Forwarded-Proto', url.protocol.replace(':', ''))

      const hasBody = !['GET', 'HEAD'].includes(request.method)
      try {
        const response = await fetch(
          new Request(target.toString(), {
            method: request.method,
            headers,
            body: hasBody ? request.body : null,
            redirect: 'manual',
          }),
        )
        // 현황판은 사람마다, 순간마다 다르다. 중간에서 저장해 두지 않게 한다.
        const proxied = new Response(response.body, response)
        proxied.headers.set('Cache-Control', 'no-store')
        return proxied
      } catch (error) {
        console.error('백엔드 호출 실패:', error)
        return Response.json(
          { status: 502, code: 'BACKEND_UNREACHABLE', message: '서버에 연결하지 못했어요. 잠시 뒤에 다시 시도해 주세요.' },
          { status: 502, headers: { 'Cache-Control': 'no-store' } },
        )
      }
    }

    const response = await env.ASSETS.fetch(request)
    const withHeaders = new Response(response.body, response)
    // 모임 링크의 토큰이 검색 결과나 다른 사이트의 접속 기록으로 새지 않게 한다.
    withHeaders.headers.set('X-Robots-Tag', 'noindex, nofollow')
    withHeaders.headers.set('Referrer-Policy', 'no-referrer')
    return withHeaders
  },
}
