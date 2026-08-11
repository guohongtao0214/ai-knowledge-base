"""LLM 调用统一客户端模块。

支持 DeepSeek、Qwen（通义千问）、OpenAI 三种模型提供商，
通过环境变量切换，使用 httpx 直接调用 OpenAI 兼容 API。
"""

import asyncio
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────── 提供商配置 ───────────────────────────

PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "pricing": {"input": 0.27, "output": 1.10},
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
        "pricing": {"input": 0.50, "output": 2.00},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "pricing": {"input": 0.15, "output": 0.60},
    },
}

DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek")
DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3


# ─────────────────────────── 数据模型 ───────────────────────────


@dataclass
class Usage:
    """Token 用量统计。

    Attributes:
        prompt_tokens: 提示词消耗 Token 数。
        completion_tokens: 生成内容消耗 Token 数。
        total_tokens: 总 Token 数。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 调用统一返回类型。

    Attributes:
        content: 模型返回的文本内容。
        usage: Token 用量统计。
        model: 实际使用的模型名称。
        finish_reason: 完成原因（stop / length / content_filter）。
    """

    content: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    finish_reason: str = ""


# ─────────────────────────── 抽象基类 ───────────────────────────


class LLMProvider(ABC):
    """LLM 调用提供商的抽象基类。"""

    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        """同步调用聊天补全接口。

        Args:
            messages: 消息列表，每条消息包含 role 和 content 字段。
            **kwargs: 其他参数（model、temperature、max_tokens 等）。

        Returns:
            LLMResponse: 统一响应对象。
        """
        ...

    @abstractmethod
    async def async_chat(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> LLMResponse:
        """异步调用聊天补全接口。

        Args:
            messages: 消息列表，每条消息包含 role 和 content 字段。
            **kwargs: 其他参数（model、temperature、max_tokens 等）。

        Returns:
            LLMResponse: 统一响应对象。
        """
        ...


# ─────────────────────────── 实现类 ───────────────────────────


class OpenAICompatibleProvider(LLMProvider):
    """基于 OpenAI 兼容 API 的 LLM 调用实现。

    通过 httpx 直接调用任何兼容 OpenAI Chat Completions 接口的模型服务。

    Attributes:
        api_key: API 密钥。
        base_url: API 基础地址。
        model: 默认模型名称。
        http_client: httpx 客户端实例。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化 OpenAI 兼容提供商。

        Args:
            api_key: API 密钥。
            base_url: API 基础地址（如 https://api.deepseek.com/v1）。
            model: 默认模型名称，不传则使用提供商默认模型。
            timeout: 请求超时时间（秒）。
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.Client:
        """延迟初始化同步 httpx 客户端。"""
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self._timeout),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    @property
    def async_client(self) -> httpx.AsyncClient:
        """延迟初始化异步 httpx 客户端。"""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._async_client

    def _build_payload(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        """构建请求体。

        Args:
            messages: 消息列表。
            **kwargs: 额外参数。

        Returns:
            请求体字典。
        """
        payload: dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
        }
        optional_fields = (
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "stream",
        )
        for field in optional_fields:
            if field in kwargs:
                payload[field] = kwargs[field]
        return payload

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """解析 API 响应为 LLMResponse。

        Args:
            data: API 返回的 JSON 数据。

        Returns:
            LLMResponse 对象。
        """
        choices = data.get("choices", [])
        if not choices:
            logger.warning("API 返回的 choices 为空")
            return LLMResponse(content="")

        message = choices[0].get("message", {})
        content = message.get("content", "") or ""

        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return LLMResponse(
            content=content,
            usage=usage,
            model=data.get("model", ""),
            finish_reason=choices[0].get("finish_reason", ""),
        )

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        """同步调用聊天补全接口。

        Args:
            messages: 消息列表，每条消息包含 role 和 content 字段。
            **kwargs: 其他参数（model、temperature、max_tokens 等）。

        Returns:
            LLMResponse: 统一响应对象。

        Raises:
            httpx.HTTPStatusError: API 返回非 2xx 状态码。
            httpx.RequestError: 网络请求异常。
        """
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, **kwargs)

        logger.info(f"同步调用 LLM: model={payload['model']}, messages={len(messages)}")
        start = time.monotonic()

        response = self.client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        elapsed = time.monotonic() - start
        result = self._parse_response(data)
        logger.info(
            f"LLM 调用完成: model={result.model}, "
            f"tokens={result.usage.total_tokens}, "
            f"elapsed={elapsed:.2f}s"
        )
        return result

    async def async_chat(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> LLMResponse:
        """异步调用聊天补全接口。

        Args:
            messages: 消息列表，每条消息包含 role 和 content 字段。
            **kwargs: 其他参数（model、temperature、max_tokens 等）。

        Returns:
            LLMResponse: 统一响应对象。

        Raises:
            httpx.HTTPStatusError: API 返回非 2xx 状态码。
            httpx.RequestError: 网络请求异常。
        """
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, **kwargs)

        logger.info(f"异步调用 LLM: model={payload['model']}, messages={len(messages)}")
        start = time.monotonic()

        response = await self.async_client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        elapsed = time.monotonic() - start
        result = self._parse_response(data)
        logger.info(
            f"LLM 调用完成: model={result.model}, "
            f"tokens={result.usage.total_tokens}, "
            f"elapsed={elapsed:.2f}s"
        )
        return result

    def close(self) -> None:
        """关闭 HTTP 客户端连接。"""
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._async_client is not None:
            # httpx.AsyncClient.aclose() 是异步方法，这里仅在同步上下文尽力关闭
            self._async_client = None

    def __enter__(self) -> "OpenAICompatibleProvider":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ─────────────────────────── Token 工具函数 ───────────────────────────

# 粗略估算：英文 ~4 字符/token，中文 ~1.5 字符/token
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]")
_EN_PATTERN = re.compile(r"[a-zA-Z0-9]+")
_SPECIAL_PATTERN = re.compile(r"[^\s\w\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]")

UTF8_PER_TOKEN_CHINESE = 1.5
UTF8_PER_TOKEN_ENGLISH = 4.0
UTF8_PER_TOKEN_SPECIAL = 1.0


def estimate_tokens(text: str) -> int:
    """估算文本的 Token 数量（无需外部 tokenizer 库）。

    使用启发式规则：中文字符约 1.5 字符/token，英文单词约 4 字符/token。

    Args:
        text: 输入文本。

    Returns:
        估算的 Token 数量。
    """
    if not text:
        return 0

    cjk_chars = len(_CJK_PATTERN.findall(text))
    en_matches = _EN_PATTERN.findall(text)
    en_chars = sum(len(m) for m in en_matches)
    special_matches = _SPECIAL_PATTERN.findall(text)
    special_chars = len(special_matches)
    other_chars = len(text) - cjk_chars - en_chars - special_chars

    estimated = (
        cjk_chars / UTF8_PER_TOKEN_CHINESE
        + en_chars / UTF8_PER_TOKEN_ENGLISH
        + special_chars / UTF8_PER_TOKEN_SPECIAL
        + other_chars / UTF8_PER_TOKEN_ENGLISH
    )
    return max(1, round(estimated))


def calculate_cost(usage: Usage, provider: str, model: str = "") -> float:
    """根据 Token 用量计算调用成本（USD）。

    Args:
        usage: Token 用量统计。
        provider: 提供商名称（deepseek / qwen / openai）。
        model: 模型名称（用于未来精细化计费）。

    Returns:
        本次调用成本（美元），保留 6 位小数。
    """
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        logger.warning(f"未知提供商 {provider}，无法计算成本")
        return 0.0

    pricing = config["pricing"]
    input_cost = (usage.prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


# ─────────────────────────── 重试与便捷函数 ───────────────────────────


async def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    max_retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> LLMResponse:
    """带自动重试的异步聊天调用，使用指数退避策略。

    失败时自动重试，退避间隔为 2^retry 秒（1s / 2s / 4s）。

    Args:
        provider: LLMProvider 实例。
        messages: 消息列表。
        max_retries: 最大重试次数，默认 3。
        **kwargs: 传递给 provider.chat 的额外参数。

    Returns:
        LLMResponse: 统一响应对象。

    Raises:
        RuntimeError: 全部重试耗尽后仍失败。
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await provider.async_chat(messages, **kwargs)
        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
            last_error = e
            if attempt < max_retries:
                wait = 2**attempt
                logger.warning(
                    f"LLM 调用失败 (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"等待 {wait}s 后重试..."
                )
                await asyncio.sleep(wait)
            else:
                logger.error(f"LLM 调用全部 {max_retries + 1} 次尝试均失败")

    raise RuntimeError(
        f"重试 {max_retries} 次后 LLM 调用仍失败"
    ) from last_error


def quick_chat(
    prompt: str,
    system: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMResponse:
    """便捷函数，一句话调用 LLM 完成聊天。

    Args:
        prompt: 用户提示词。
        system: 系统提示词（可选）。
        provider: 提供商名称，默认读取 LLM_PROVIDER 环境变量。
        model: 模型名称，不传则使用提供商默认模型。
        api_key: API 密钥，不传则从环境变量自动查找。

    Returns:
        LLMResponse: 统一响应对象。

    Raises:
        ValueError: API 密钥未找到。

    Example:
        >>> resp = quick_chat("解释什么是 MCP 协议")
        >>> print(resp.content)
    """
    provider_name = provider or DEFAULT_PROVIDER
    config = PROVIDER_CONFIGS.get(provider_name)
    if not config:
        raise ValueError(f"未知提供商: {provider_name}")

    if api_key is None:
        api_key = os.environ.get(config["api_key_env"], "")
        if not api_key:
            api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise ValueError(
            f"{provider_name} 的 API Key 未设置，"
            f"请设置环境变量 {config['api_key_env']} 或 LLM_API_KEY"
        )

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    client = OpenAICompatibleProvider(
        api_key=api_key,
        base_url=config["base_url"],
        model=model or config["default_model"],
    )
    try:
        return client.chat(messages)
    finally:
        client.close()


def create_provider(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> OpenAICompatibleProvider:
    """工厂函数，根据环境变量创建 LLM 提供商实例。

    Args:
        provider: 提供商名称（deepseek / qwen / openai），默认读取 LLM_PROVIDER 环境变量。
        model: 模型名称，不传则使用提供商默认模型。
        api_key: API 密钥，不传则从环境变量自动查找。

    Returns:
        OpenAICompatibleProvider 实例。

    Raises:
        ValueError: 提供商未知或 API 密钥未配置。
    """
    provider_name = provider or DEFAULT_PROVIDER
    config = PROVIDER_CONFIGS.get(provider_name)
    if not config:
        raise ValueError(f"未知提供商: {provider_name}")

    if api_key is None:
        api_key = os.environ.get(config["api_key_env"], "")
        if not api_key:
            api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise ValueError(
            f"{provider_name} 的 API Key 未设置，"
            f"请设置环境变量 {config['api_key_env']} 或 LLM_API_KEY"
        )

    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=config["base_url"],
        model=model or config["default_model"],
    )


# ─────────────────────────── 测试代码 ───────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("测试 1: estimate_tokens()")
    print("=" * 60)
    samples = [
        (
            "Hello, how are you? This is a sample English text for token estimation.",
            15,
        ),
        ("人工智能正在改变世界的每一个角落，深度学习让机器学会了看、听和理解。", 20),
        ("", 0),
    ]
    for text, expected_range_max in samples:
        tokens = estimate_tokens(text)
        print(f"  文本 ({len(text)} chars): {text[:40]}...")
        print(f"    估算 Token: {tokens}")
        print()

    print("=" * 60)
    print("测试 2: calculate_cost()")
    print("=" * 60)
    providers_to_test = ["deepseek", "openai"]
    for prov in providers_to_test:
        usage = Usage(prompt_tokens=5000, completion_tokens=2000, total_tokens=7000)
        cost = calculate_cost(usage, prov)
        pricing = PROVIDER_CONFIGS[prov]["pricing"]
        print(f"  {prov}: prompt=5000 output=2000")
        print(f"    定价: input=${pricing['input']}/1M, output=${pricing['output']}/1M")
        print(f"    估算成本: ${cost}")
        print()

    print("=" * 60)
    print("测试 3: quick_chat() — 需要在以下环境变量之一有效才能通过")
    print(f"  LLM_PROVIDER={DEFAULT_PROVIDER}")
    for prov, cfg in PROVIDER_CONFIGS.items():
        key = os.environ.get(cfg["api_key_env"], "")
        masked = key[:6] + "..." if len(key) > 6 else "(未设置)"
        print(f"  {cfg['api_key_env']}={masked}")
    print(f"  LLM_API_KEY={'***' if os.environ.get('LLM_API_KEY') else '(未设置)'}")
    print("=" * 60)

    try:
        resp = quick_chat("用一句话介绍 Python 语言")
        print(f"  model: {resp.model}")
        print(f"  content: {resp.content[:150]}...")
        print(f"  usage: prompt={resp.usage.prompt_tokens}, "
              f"completion={resp.usage.completion_tokens}, "
              f"total={resp.usage.total_tokens}")
        cost = calculate_cost(resp.usage, DEFAULT_PROVIDER)
        print(f"  cost: ${cost}")
    except ValueError as e:
        print(f"  [跳过] API Key 未配置: {e}")
    except Exception as e:
        print(f"  [错误] {type(e).__name__}: {e}")
