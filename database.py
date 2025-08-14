import chromadb

# --- ChromaDB Client and Collection ---
CHROMA_DB_PATH = "./chroma_db"
COLLECTION_NAME = "bank_users"
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)


class UserDatabase:
    def __init__(self):
        self.collection = client.get_or_create_collection(name=COLLECTION_NAME)

    def get_next_account_number(self):
        users = self.collection.get()
        if not users["ids"]:
            return "00001"
        max_num = max(int(meta["account_number"]) for meta in users["metadatas"])
        return f"{max_num+1:05d}"

    def user_exists_by_account(self, account_number):
        result = self.collection.get(ids=[account_number])
        return bool(result.get("ids"))

    def user_exists_by_name(self, full_name):
        users = self.collection.get()
        for meta in users["metadatas"]:
            if meta["full_name"].lower() == full_name.lower():
                return True
        return False

    def add_user(self, first_name, middle_name, last_name, dob, address):
        full_name = f"{first_name} {middle_name} {last_name}".strip()
        if self.user_exists_by_name(full_name):
            return None
        account_number = self.get_next_account_number()
        user_data = {
            "full_name": full_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "dob": dob,
            "address": address,
            "account_number": account_number
        }
        self.collection.add(
            documents=[str(user_data)],
            metadatas=[user_data],
            ids=[account_number],
        )
        return account_number

    def get_user_by_account(self, account_number):
        result = self.collection.get(ids=[account_number])
        if result["documents"]:
            return result["metadatas"][0]
        return None

    def get_user_by_name(self, full_name):
        users = self.collection.get()
        for meta in users["metadatas"]:
            if meta["full_name"].lower() == full_name.lower():
                return meta
        return None