from pymongo import AsyncMongoClient

from app.data.config import MONGO_NAME, MONGO_URL

client = AsyncMongoClient(MONGO_URL)
database = client[MONGO_NAME]
