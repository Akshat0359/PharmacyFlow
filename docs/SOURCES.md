# Official references consulted

Documentation was consulted before provider integration work, November 12–13, 2026. The dependency lock records the exact compatible releases actually installed; documentation may describe newer releases. Live credentials were not used.

- [OpenAI Python API](https://developers.openai.com/api/reference/python): Responses calls and configurable client.
- [OpenAI audio and voice](https://developers.openai.com/api/docs/guides/audio): transcription → application workflow → speech generation. This app uses recorded audio turns, not a real-time duplex call.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): durable thread/checkpoint model and backend selection.
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk): FastMCP server, typed tools, Streamable HTTP client session.
- [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/) and [Agentic Top 10 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/): implementation mapping in SECURITY.md.
- [Compose startup ordering](https://docs.docker.com/compose/how-tos/startup-order/): readiness and migration gates.
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https): domain-based cloud TLS requirements.
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/install/) and [Jaeger deployment](https://www.jaegertracing.io/docs/2.5/deployment/): local OTLP trace pipeline. Container startup remains unverified without Docker.

No quoted clinical guidelines or real pharmacy SOPs are included. The policy corpus and medication names are deliberately fictional.
