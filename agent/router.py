import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
import logging
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

# Çok dilli embedding modeli
multilingual_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)

# Router için ayrı ChromaDB koleksiyonu
router_client = chromadb.Client()
try:
    router_client.delete_collection("router")
except:
    pass
router_collection = router_client.get_or_create_collection(
    name="router",
    embedding_function=multilingual_ef
)

# Örnek sorular
simple_questions = [
    "TK3 hızı kaç?",
    "Kaç uçuş havada?",
    "En hızlı uçuş hangisi?",
    "New York'a giden uçuş var mı?",
    "Londra'dan gelen uçuş var mı?",
    "TK12 nereye gidiyor?",
    "En yavaş uçuş hangisi?",
    "Destinasyonlar neler?",
    "Tokyo'dan gelen uçuş var mı?",
    "Boeing B77W kullanan uçuşlar hangileri?",
    "TK51 irtifası kaç?",
    "Doha'dan gelen uçuş var mı?",
    "Frankfurt'tan kaç sefer var?",
    "En uzun uçuş hangisi?",
    "TK3 havada mı?",
    "Kaç farklı destinasyon var?",
    "TK12 uçak tipi nedir?",
    "İstanbul'dan en çok nereye uçuş var?",
    "TK3 nereye gidiyor?",
    "En hızlı uçuşun hızı kaç?",
]

complex_questions = [
    "TK3'ün hızı tüm uçuşların ortalamasından yüksek mi?",
    "Boeing B77W kullanan uçuşların ortalama irtifası kaç?",
    "En hızlı 3 uçuşu karşılaştır",
    "Frankfurt'tan gelen uçuşların ortalama hızı nedir?",
    "Havadaki uçuşların hız dağılımı nedir?",
    "TK3 ve TK12 hangisi daha hızlı?",
    "En hızlı uçuş ortalamadan kaç kat daha hızlı?",
    "Havadaki uçuşların irtifa ortalaması kaç?",
    "B77W ve A333 uçaklarının ortalama hızını karşılaştır",
    "En hızlı 5 uçuşun ortalama irtifası nedir?",
    "IST JFK güzergahındaki uçuşların hız dağılımı nedir?",
    "Hangi havayolu en çok uçuş yapıyor?",
    "Avrupa seferlerinin ortalama irtifası Asya seferlerinden yüksek mi?",
    "En hızlı uçuş ile en yavaş uçuş arasındaki hız farkı nedir?",
    "Havadaki uçuşların ortalama hızı kaç?",
    "TK uçuşlarının ortalama irtifası diğerlerinden yüksek mi?",
    "En çok hangi uçak tipi kullanılıyor?",
    "Hangi güzergah en yoğun?",
    "B77W uçuşlarının ortalama hızı A333 uçuşlarından yüksek mi?",
    "En hızlı 10 uçuşun ortalama irtifası nedir?",
]

# İndexle
documents = simple_questions + complex_questions
ids = [f"simple_{i}" for i in range(len(simple_questions))] + \
      [f"complex_{i}" for i in range(len(complex_questions))]
metadatas = [{"type": "simple"}] * len(simple_questions) + \
            [{"type": "complex"}] * len(complex_questions)

router_collection.upsert(
    documents=documents,
    ids=ids,
    metadatas=metadatas
)

logger.info(f"Router indexlendi: {len(simple_questions)} basit, {len(complex_questions)} karmaşık soru")

def detect_complexity(soru):
    results = router_collection.query(
        query_texts=[soru],
        n_results=5
    )

    types = results["metadatas"][0]
    distances = results["distances"][0]

    # Ağırlıklı oy
    complex_score = 0
    simple_score = 0

    for t, d in zip(types, distances):
        weight = 1 / (1 + d)
        if t["type"] == "complex":
            complex_score += weight
        else:
            simple_score += weight

    complexity = "complex" if complex_score > simple_score else "simple"
    logger.info(f"Router: {'Groq' if complexity == 'complex' else 'Cohere'} | Soru: {soru} | complex_score: {complex_score:.2f} simple_score: {simple_score:.2f}")
    return complexity