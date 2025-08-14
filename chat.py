import google.generativeai as genai
from config import get_gemini_api_key, BANKAI_PERSONA
import datetime
import os
import json
import chromadb

# Directory for storing session metadata JSON files
SESSIONS_DATA_DIR = "./sessions_data"

class BankaiChat:
    def __init__(self, chroma_db_path="./chroma_db"):
        print("BankaiChat: Initializing...")
        genai.configure(api_key=get_gemini_api_key())
        self.base_model = genai.GenerativeModel(
            model_name='gemini-pro', # Using gemini-pro, change if you need a different model
            system_instruction=BANKAI_PERSONA
        )
        self.sessions = {} # In-memory cache for active chat sessions and their metadata/chat_session objects

        # Initialize ChromaDB client and collection
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)
        self.collection = self.chroma_client.get_or_create_collection("chatbot_conversation_history")
        print(f"BankaiChat: ChromaDB initialized at {chroma_db_path}")

        # Ensure the sessions_data directory exists
        os.makedirs(SESSIONS_DATA_DIR, exist_ok=True)
        print(f"BankaiChat: Sessions data directory at {SESSIONS_DATA_DIR}")
        
        # Load all existing session metadata from JSON files on startup
        self._load_all_session_metadata()
        print(f"BankaiChat: Loaded {len(self.sessions)} existing session metadata files.")

    def _load_all_session_metadata(self):
        """Loads basic session metadata from JSON files into self.sessions cache."""
        for filename in os.listdir(SESSIONS_DATA_DIR):
            if filename.endswith(".json"):
                session_id = filename.replace(".json", "")
                filepath = os.path.join(SESSIONS_DATA_DIR, filename)
                try:
                    with open(filepath, 'r') as f:
                        metadata = json.load(f)
                        self.sessions[session_id] = {
                            "title": metadata.get("title"),
                            "user_info": metadata.get("user_info", {}),
                            "current_step": metadata.get("current_step", "welcome"),
                            "account_confirmed": metadata.get("account_confirmed", False),
                            "history": [], # History will be loaded from ChromaDB when session is explicitly accessed
                            "chat_session": None # Gemini chat session will be initialized on demand
                        }
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON from {filepath}. Skipping.")
                except Exception as e:
                    print(f"Error loading session metadata from {filepath}: {e}")

    def _initialize_session(self, session_id):
        """
        Ensures a session's metadata is loaded, its message history is retrieved from ChromaDB,
        and the Gemini chat session is initialized with that history.
        This is called whenever a session's data (history, state) is needed.
        """
        # Load basic metadata if not already in cache (e.g., accessed for first time after startup)
        if session_id not in self.sessions:
            filepath = os.path.join(SESSIONS_DATA_DIR, f"{session_id}.json")
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r') as f:
                        metadata = json.load(f)
                        self.sessions[session_id] = {
                            "title": metadata.get("title"),
                            "user_info": metadata.get("user_info", {}),
                            "current_step": metadata.get("current_step", "welcome"),
                            "account_confirmed": metadata.get("account_confirmed", False),
                            "history": [],
                            "chat_session": None
                        }
                    print(f"BankaiChat: Loaded metadata for {session_id} from file during _initialize_session.")
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON from {filepath}. Creating new metadata defaults for session {session_id}.")
                    self.sessions[session_id] = { # Default for corrupted metadata
                        "title": None, "user_info": {}, "current_step": "welcome", "account_confirmed": False, "history": [], "chat_session": None
                    }
            else: # Truly new session, no metadata file exists yet
                print(f"BankaiChat: Creating new session {session_id} with default metadata during _initialize_session.")
                self.sessions[session_id] = {
                    "title": None, "user_info": {}, "current_step": "welcome", "account_confirmed": False, "history": [], "chat_session": None
                }

        # Initialize/re-initialize Gemini chat session if not already done or if it's None
        if self.sessions[session_id]["chat_session"] is None:
            # Load message history from ChromaDB for this specific session
            results = self.collection.get(
                where={"session_id": session_id},
                include=['documents', 'metadatas']
            )
            
            loaded_messages = []
            if results and results['ids']:
                for i in range(len(results['ids'])):
                    metadata = results['metadatas'][i]
                    # Ensure 'timestamp' exists and is valid for sorting
                    if 'timestamp' in metadata:
                        loaded_messages.append({
                            "role": metadata['role'],
                            "text": results['documents'][i],
                            "timestamp": metadata['timestamp']
                        })
                
                # Sort messages by timestamp to reconstruct correct chronological order
                loaded_messages.sort(key=lambda x: datetime.datetime.fromisoformat(x['timestamp']))
            
            # Update the in-memory session history
            self.sessions[session_id]["history"] = [{ "role": msg["role"], "text": msg["text"] } for msg in loaded_messages]
            print(f"BankaiChat: Loaded {len(loaded_messages)} messages from ChromaDB for session {session_id}")

            # Prepare history for Gemini API (convert roles as required by API)
            gemini_history = []
            for msg in loaded_messages:
                # Gemini API expects 'user' and 'model' roles
                role_for_gemini = "user" if msg["role"] == "You" else "model"
                gemini_history.append({"role": role_for_gemini, "parts": [msg["text"]]})
            
            # Initialize the actual Gemini chat session with loaded history
            self.sessions[session_id]["chat_session"] = self.base_model.start_chat(history=gemini_history)
            print(f"BankaiChat: Gemini chat session initialized for {session_id} with {len(gemini_history)} turns.")


    def _save_session_metadata(self, session_id):
        """Saves the current session's metadata to its JSON file."""
        filepath = os.path.join(SESSIONS_DATA_DIR, f"{session_id}.json")
        metadata_to_save = {
            "title": self.sessions[session_id].get("title"),
            "user_info": self.sessions[session_id].get("user_info", {}),
            "current_step": self.sessions[session_id].get("current_step", "welcome"),
            "account_confirmed": self.sessions[session_id].get("account_confirmed", False)
        }
        try:
            with open(filepath, 'w') as f:
                json.dump(metadata_to_save, f, indent=4)
            # print(f"BankaiChat: Saved metadata for session {session_id} to {filepath}")
        except Exception as e:
            print(f"Error saving session metadata for {session_id}: {e}")

    def get_session(self, session_id):
        """Retrieves and initializes a session."""
        self._initialize_session(session_id)
        return self.sessions[session_id]

    def send_message_in_session(self, session_id, message):
        self._initialize_session(session_id)
        chat_session = self.sessions[session_id]["chat_session"]
        
        response_text = None # Initialize response_text to None

        # --- Hardcoded/Guided Flow Responses for Speed ---
        # Using .lower() for case-insensitivity
        if "user wants to open an account" in message.lower():
            response_text = "Great! Let's get started with opening your new bank account. To begin, I'll need some personal information. First, what is your **full legal name** (First, Middle, Last)?"
        elif "user provided name." in message.lower():
            response_text = "Thank you. What is your **date of birth** (YYYY-MM-DD)?"
        elif "user provided dob." in message.lower():
            response_text = "Next, could you provide your current **residential address**?"
        elif "user provided address." in message.lower():
            response_text = "Thank you for providing those details. The next step is to verify your identity. This is a crucial security step to protect your new account. Please prepare your valid government-issued ID (e.g., Kebele ID, Passport, or Driver's License). Place it on a flat, well-lit surface. Take a clear photo of the **front side** of the ID. Ensure all four corners are visible and there is no glare. Your security is our top priority. This upload is encrypted. Please use the button below to upload the photo of your ID."
        elif "user uploaded id front." in message.lower():
            response_text = "Perfect, thank you. I've successfully received the front of your ID. Now, please upload a clear photo of the **back side** of your ID."
        elif "user uploaded both sides of id." in message.lower():
            response_text = "Great! I've now received both sides of your ID and we're verifying the details. Once verified, I'll summarize everything for your confirmation."
        
        # --- Fallback to Actual Gemini API for General Queries ---
        if response_text is None: # If no hardcoded response matched, hit the actual Gemini API
            print(f"BankaiChat: Sending '{message[:50]}...' to Gemini API for session {session_id}...")
            try:
                # The send_message call should append to the chat_session's internal history
                response_stream = chat_session.send_message(message, stream=True)
                response_parts = []
                for chunk in response_stream:
                    if chunk.text: # Only append if chunk has text
                        response_parts.append(chunk.text)
                response_text = "".join(response_parts).strip() # .strip() removes leading/trailing whitespace

                if not response_text: # If still empty after stripping
                    response_text = "I'm sorry, I couldn't generate a specific response for that. Could you please rephrase?"
                    print(f"BankaiChat: Gemini returned an empty response for session {session_id}. Fallback activated.")
                else:
                    print(f"BankaiChat: Gemini responded: '{response_text[:50]}...' for session {session_id}")

            except genai.types.BlockedPromptException as e:
                response_text = "I'm sorry, your request was blocked due to safety concerns. Please try a different query."
                print(f"BankaiChat: BlockedPromptException for session {session_id}: {e}")
            except Exception as e:
                response_text = f"I'm sorry, I couldn't process that. An internal error occurred: {e}"
                print(f"Error calling Gemini API for session {session_id}: {e}")
        
        return response_text

    def add_message_to_session(self, session_id, message_dict):
        """Adds a message to the in-memory session history and persists to ChromaDB."""
        self._initialize_session(session_id) # Ensure session is loaded/initialized before adding message
        self.sessions[session_id]["history"].append(message_dict)

        # Add to ChromaDB
        # Ensure timestamp is unique enough using ISO format with microseconds
        timestamp_iso = datetime.datetime.now().isoformat(timespec='microseconds')
        # Replace characters that might be problematic in IDs if not careful (though Chroma handles many)
        doc_id = f"{session_id}_{timestamp_iso.replace(':', '_').replace('.', '_')}_{message_dict['role']}"
        
        try:
            self.collection.add(
                documents=[message_dict['text']],
                metadatas=[{"session_id": session_id, "role": message_dict['role'], "timestamp": timestamp_iso}],
                ids=[doc_id]
            )
            print(f"BankaiChat: Added message to ChromaDB for session {session_id}")
        except Exception as e:
            print(f"Error adding message to ChromaDB for session {session_id}: {e}")


    def get_session_history(self, session_id):
        """Returns the in-memory history for a session (loaded from ChromaDB)."""
        self._initialize_session(session_id)
        return self.sessions[session_id]["history"]

    def get_all_session_ids(self):
        """Returns all known session IDs from metadata files."""
        # This will return IDs from the already loaded metadata during __init__
        return list(self.sessions.keys())

    def set_session_title(self, session_id, title):
        self._initialize_session(session_id)
        self.sessions[session_id]["title"] = title
        self._save_session_metadata(session_id) # Persist change

    def get_session_title(self, session_id):
        self._initialize_session(session_id)
        return self.sessions[session_id]["title"]

    def set_session_user_info(self, session_id, user_info):
        self._initialize_session(session_id)
        self.sessions[session_id]["user_info"] = user_info
        self._save_session_metadata(session_id) # Persist change

    def get_session_user_info(self, session_id):
        self._initialize_session(session_id)
        return self.sessions[session_id]["user_info"]

    def set_session_current_step(self, session_id, step):
        self._initialize_session(session_id)
        self.sessions[session_id]["current_step"] = step
        self._save_session_metadata(session_id) # Persist change

    def get_session_current_step(self, session_id):
        self._initialize_session(session_id)
        return self.sessions[session_id]["current_step"]

    def set_session_account_confirmed(self, session_id, confirmed):
        self._initialize_session(session_id)
        self.sessions[session_id]["account_confirmed"] = confirmed
        self._save_session_metadata(session_id) # Persist change

    def get_session_account_confirmed(self, session_id):
        self._initialize_session(session_id)
        return self.sessions[session_id]["account_confirmed"]

    def mark_session_account_created(self, session_id):
        self.set_session_account_confirmed(session_id, True)

    def delete_session(self, session_id):
        """Deletes all data for a given session from in-memory, file system, and ChromaDB."""
        print(f"BankaiChat: Deleting session {session_id}...")
        # 1. Delete from in-memory cache
        if session_id in self.sessions:
            del self.sessions[session_id]
        
        # 2. Delete session metadata file
        filepath = os.path.join(SESSIONS_DATA_DIR, f"{session_id}.json")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"BankaiChat: Deleted session metadata file: {filepath}")
            except Exception as e:
                print(f"Error deleting session metadata file {filepath}: {e}")
        
        # 3. Delete messages from ChromaDB
        try:
            # Delete documents from the collection where session_id matches
            self.collection.delete(where={"session_id": session_id})
            print(f"BankaiChat: Deleted messages from ChromaDB for session: {session_id}")
        except Exception as e:
            print(f"Error deleting from ChromaDB for session {session_id}: {e}")

    # generate_session_title is removed as per requirement to use first user request as title
    # def generate_session_title(self, session_id):
    #    ...