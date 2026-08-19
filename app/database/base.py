from pymongo import AsyncMongoClient

from app.config import MONGO_NAME, MONGO_URL

client = AsyncMongoClient(MONGO_URL)
database = client[MONGO_NAME]
