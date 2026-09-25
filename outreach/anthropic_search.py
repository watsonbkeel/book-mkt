"""Bounded Anthropic Messages transport, including the basic native search tool.

No local tool execution. Native search results are discovery hints; Researcher
still fetches owner pages and independently verifies contact and location text.
"""
from __future__ import annotations

MAX_SEARCH_USES = 4
MAX_CONTINUATIONS = 2
BASIC_SEARCH_TOOL = 'web_search_20250305'


def messages_call(ai, cfg, key, model, instructions, prompt, usage_id, *, research=False):
    from .ai import ProviderError

    messages = [{'role':'user', 'content':prompt}]
    search_calls = set()
    resolved_calls = set()
    sources = []
    current_id = usage_id
    max_turns = MAX_CONTINUATIONS + 1 if research else 1
    for turn in range(max_turns):
        if turn:
            current_id = ai.reserve('llm')
            ai.store.execute('UPDATE api_usage SET model=?,purpose=? WHERE id=?',
                             (model, 'research_continuation', current_id))
        payload = {
            'model':model,
            'system':instructions + ' Return the final answer as one JSON object, no prose or markdown.',
            'messages':messages,
            'max_tokens':5500 if research else 2200,
        }
        if research:
            remaining = MAX_SEARCH_USES - len(search_calls)
            if remaining <= 0:
                ai.store.execute("UPDATE api_usage SET status='failed' WHERE id=?", (current_id,))
                raise ProviderError('本轮原生搜索工具次数已达上限；不继续调用或编造结果')
            payload['tools'] = [{'type':BASIC_SEARCH_TOOL, 'name':'web_search','max_uses':remaining}]
        try:
            response = ai.http.json(cfg['api_base_url'] + '/messages', payload=payload,
                                   headers={'x-api-key':key, 'anthropic-version':'2023-06-01'})
            usage = response.get('usage') or {}
            ai.store.execute('UPDATE api_usage SET input_tokens=?,output_tokens=? WHERE id=?',
                             (int(usage.get('input_tokens',0) or 0),
                              int(usage.get('output_tokens',0) or 0), current_id))
            content = response.get('content')
            if not isinstance(content, list):
                raise ProviderError('Messages返回内容不是列表')
            last_result = -1
            for index, block in enumerate(content):
                if not isinstance(block, dict):
                    raise ProviderError('Messages内容块格式不正确')
                kind = block.get('type')
                if kind == 'server_tool_use':
                    if not research or block.get('name') != 'web_search' or not block.get('id'):
                        raise ProviderError('收到未授权的服务器工具请求')
                    search_calls.add(block['id'])
                    if len(search_calls) > MAX_SEARCH_USES:
                        raise ProviderError('提供方搜索调用数超过程序预算')
                elif kind == 'web_search_tool_result':
                    call_id = block.get('tool_use_id')
                    if call_id not in search_calls:
                        raise ProviderError('搜索结果未匹配实际工具调用')
                    results = block.get('content')
                    if not isinstance(results, list):
                        # HTTP200 may still contain unavailable/rate-limit/search errors.
                        raise ProviderError('原生web_search返回工具错误，不把HTTP200当研究成功')
                    for row in results:
                        if not isinstance(row, dict) or row.get('type') != 'web_search_result':
                            raise ProviderError('原生搜索返回未知结果类型')
                        if isinstance(row.get('url'), str):
                            item = {'url':row['url'], 'title':str(row.get('title',''))[:300]}
                            if item not in sources:
                                sources.append(item)
                    resolved_calls.add(call_id)
                    last_result = index
                elif kind in ('tool_use', 'tool_result'):
                    raise ProviderError('不执行模型提出的本地工具或任意网页操作')
            reason = response.get('stop_reason')
            if reason == 'pause_turn' and research:
                if turn >= MAX_CONTINUATIONS or len(search_calls) >= MAX_SEARCH_USES:
                    raise ProviderError('原生搜索多轮暂停达到上限，保留失败状态，不自动循环')
                # Preserve opaque encrypted_content and every other field exactly.
                messages = messages + [{'role':'assistant', 'content':content}]
                ai.store.execute("UPDATE api_usage SET status='continued' WHERE id=?", (current_id,))
                continue
            if reason != 'end_turn':
                raise ProviderError('Messages未完整结束；不使用截断答案')
            if research and (not search_calls or resolved_calls != search_calls):
                raise ProviderError('缺少完整实际搜索证据，不把模型记忆当网页研究')
            # Discard pre-tool commentary. Only the final text segment may contain candidate JSON.
            chunks = [b.get('text','') for b in content[last_result + 1:] if b.get('type') == 'text']
            if not chunks:
                raise ProviderError('Messages缺少最终JSON文字')
            ai.store.execute("UPDATE api_usage SET status='received' WHERE id=?", (current_id,))
            return '\n'.join(chunks), sources[:40], current_id
        except Exception:
            ai.store.execute("UPDATE api_usage SET status='failed' WHERE id=?", (current_id,))
            raise
    raise ProviderError('Messages未完成')
