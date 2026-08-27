"""兼容旧导入；新代码使用 app.integrations.model。"""

import os

from app.integrations.model import (
    ModelConfigurationError,
    ModelInvocationError,
    ModelResult,
    StructuredAIModel,
)

class DeepSeekModel(StructuredAIModel):
    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        super().__init__(
            provider="deepseek",
            api_key=api_key,
            model=model,
            base_url=base_url,
            use_responses_api=False,
        )

    @classmethod
    def from_env(cls) -> "DeepSeekModel":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ModelConfigurationError("DEEPSEEK_API_KEY 未配置")
        return cls(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
        )

__all__ = [
    "DeepSeekModel",
    "ModelConfigurationError",
    "ModelInvocationError",
    "ModelResult",
]
