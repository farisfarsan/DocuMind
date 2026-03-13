from groq import Groq
from app.core.config import settings

client = Groq(api_key=settings.GROQ_API_KEY)


def build_prompt(question: str, chunks: list) -> str:
    """
    Combine the retrieved chunks + user question into a single prompt.
    """
    context = "\n\n".join([
        f"[Chunk {i+1}]:\n{chunk.content}"
        for i, chunk in enumerate(chunks)
    ])

    prompt = f"""You are a helpful assistant. Answer the question using ONLY the context provided below.
If the answer is not in the context, say "I couldn't find that in the document."

Context:
{context}

Question: {question}

Answer:"""

    return prompt


def ask_groq(question: str, chunks: list) -> str:
    """
    Build the prompt from chunks and send it to Groq.
    Returns the LLM's answer as a string.
    """
    prompt = build_prompt(question, chunks)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.2,
        max_tokens=1000,
    )

    return response.choices[0].message.content