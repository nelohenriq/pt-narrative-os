#!/usr/bin/env python3
"""Measure actual cosine similarity between text1 and text2 embeddings."""
import asyncio, os, uuid, datetime as _dt
from dotenv import load_dotenv
from openai import AsyncOpenAI
from services.clustering.embedder import _cosine_similarity

async def main():
    load_dotenv()
    ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
    client = AsyncOpenAI(base_url=f'{ollama_host}/v1', api_key='ollama')
    token = uuid.uuid4().hex

    text1 = (
        f'A nova aplicação móvel {token} desenvolvida por estudantes da '
        f'Universidade do Minho venceu o concurso nacional de inovação '
        f'tecnológica. A aplicação utiliza inteligência artificial para '
        f'otimizar rotas de transportes públicos em cidades de média '
        f'dimensão e já está a ser testada em Braga e Guimarães.'
    )
    text2 = (
        f'A aplicação móvel {token} dos estudantes do Minho que ganhou '
        f'o prémio nacional de inovação vai ser implementada em mais '
        f'cinco cidades portuguesas até ao final do ano. O projeto '
        f'recebeu também financiamento europeu de dois milhões de euros '
        f'para expandir a tecnologia de otimização de transportes.'
    )

    # Get embeddings (with search_document prefix like the real code)
    resp1 = await client.embeddings.create(
        model='nomic-embed-text', input=[f'search_document: {text1}'],
    )
    resp2 = await client.embeddings.create(
        model='nomic-embed-text', input=[f'search_document: {text2}'],
    )
    emb1 = resp1.data[0].embedding
    emb2 = resp2.data[0].embedding

    sim = _cosine_similarity(emb1, emb2)
    print(f'Cosine similarity between text1 and text2: {sim:.4f}')
    print(f'Threshold: 0.85 → {"MATCH" if sim >= 0.85 else "NO MATCH"}')

asyncio.run(main())