from openai import AsyncOpenAI

from planner.errors import WriterError
from planner.llm.prompts import build_prompt


class ItineraryWriter:
    def __init__(self, model: str) -> None:
        self.model = model
        self.client = AsyncOpenAI()

    async def write(self, city: str, forecast: list[str], spots: list[str]) -> str:
        prompt = build_prompt(city, forecast, spots)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content
        if not text:
            raise WriterError(city)
        return text
