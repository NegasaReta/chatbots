import streamlit as st
import google.generativeai as genai
import chromadb
from dotenv import load_dotenv
import os
from PIL import Image
import io
import datetime
import time # For potential use in debugging or visual delays

# Importing from local files
from chat import BankaiChat
from database import UserDatabase


# --- Configuration ---
load_dotenv()

try:
    api_key_check = os.getenv("GOOGLE_API_KEY") or st.secrets["API_KEY"]
    if not api_key_check:
        raise KeyError("API_KEY not found")
except KeyError:
    st.error("Gemini API key not found. Please set the GOOGLE_API_KEY environment variable or in Streamlit secrets.")
    st.stop()


# --- Streamlit App Setup ---

st.set_page_config(page_title="Bankai: Cooperative Bank of Oromia", page_icon="🏦")
st.title("🏦 Bankai: Cooperative Bank of Oromia")

# --- App Initialization (Cached Instances) ---
# Use st.session_state to ensure these objects persist across reruns.
# They are initialized only once per user session.
if "bankai_chat_manager" not in st.session_state:
    st.session_state.bankai_chat_manager = BankaiChat(chroma_db_path="./chroma_db")
if "user_db" not in st.session_state:
    st.session_state.user_db = UserDatabase()

# Initialize session-specific UI states
if "current_chat_session_id" not in st.session_state:
    # Attempt to load the most recent session if available, otherwise create a new one
    all_sessions = st.session_state.bankai_chat_manager.get_all_session_ids()
    if all_sessions:
        # Sort sessions by ID (which includes timestamp) to get the latest
        latest_session_id = sorted(all_sessions, reverse=True)[0]
        st.session_state.current_chat_session_id = latest_session_id
    else:
        # Create a new unique session ID if no existing sessions
        st.session_state.current_chat_session_id = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    
    # Ensure the session and its data are loaded into the manager and UI state
    st.session_state.bankai_chat_manager.get_session(st.session_state.current_chat_session_id)
    st.session_state.user_info = st.session_state.bankai_chat_manager.get_session_user_info(st.session_state.current_chat_session_id)
    st.session_state.current_step = st.session_state.bankai_chat_manager.get_session_current_step(st.session_state.current_chat_session_id)
    st.session_state.account_confirmed = st.session_state.bankai_chat_manager.get_session_account_confirmed(st.session_state.current_chat_session_id)

# Flag to determine if the initial greeting needs to be shown for the current session
# It's True if the current session already has messages, False if it's genuinely new
if "conversation_started_in_current_session" not in st.session_state:
    st.session_state.conversation_started_in_current_session = bool(st.session_state.bankai_chat_manager.get_session_history(st.session_state.current_chat_session_id))


# Helper function to add messages to the current session and persist them
def add_message_to_current_session(role, text, session_id=None):
    if session_id is None:
        session_id = st.session_state.current_chat_session_id
    
    st.session_state.bankai_chat_manager.add_message_to_session(session_id, {"role": role, "text": text})

    # When the first user message is added, set the session title if not already set
    if role == "You" and not st.session_state.bankai_chat_manager.get_session_title(session_id):
        st.session_state.bankai_chat_manager.set_session_title(session_id, text) # Use first user message as title


# --- Sidebar for Chat History Titles ---
with st.sidebar:
    st.header("Your Chats")
    
    # Button to start a new chat session
    if st.button("➕ Start New Chat", use_container_width=True):
        # Save current session's state before switching
        st.session_state.bankai_chat_manager.set_session_user_info(st.session_state.current_chat_session_id, st.session_state.user_info)
        st.session_state.bankai_chat_manager.set_session_current_step(st.session_state.current_chat_session_id, st.session_state.current_step)
        st.session_state.bankai_chat_manager.set_session_account_confirmed(st.session_state.current_chat_session_id, st.session_state.account_confirmed)
        
        # Create a new unique session ID
        new_session_id = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
        st.session_state.current_chat_session_id = new_session_id
        
        # Ensure the new session is initialized in the manager
        st.session_state.bankai_chat_manager.get_session(new_session_id)
        
        # Reset UI states for the new chat
        st.session_state.user_info = {}
        st.session_state.current_step = "welcome"
        st.session_state.account_confirmed = False
        st.session_state.conversation_started_in_current_session = False
        st.rerun() # Trigger a rerun to display the new chat interface

    st.markdown("---")
    
    # Organize and display chat sessions by day
    all_sessions_ids = st.session_state.bankai_chat_manager.get_all_session_ids()
    
    if not all_sessions_ids:
        st.write("No chat history yet.")
    else:
        sessions_by_date = {}
        for session_id in all_sessions_ids:
            try:
                date_part = session_id.split('_')[0] # Extract date from session_id (e.g., 'YYYY-MM-DD')
                session_date = datetime.datetime.strptime(date_part, '%Y-%m-%d').date()
            except ValueError:
                session_date = datetime.date.min # Fallback for malformed IDs (shouldn't happen with new ID format)

            date_str = session_date.strftime('%Y-%m-%d')
            if date_str not in sessions_by_date:
                sessions_by_date[date_str] = []
            sessions_by_date[date_str].append(session_id)
        
        # Sort dates in descending order (most recent day first)
        sorted_dates = sorted(sessions_by_date.keys(), reverse=True)

        for date_str in sorted_dates:
            date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            if date_obj == datetime.date.today():
                date_label = "Today"
            elif date_obj == datetime.date.today() - datetime.timedelta(days=1):
                date_label = "Yesterday"
            else:
                date_label = date_obj.strftime("%Y-%m-%d")
            
            # Use an expander for each day to toggle visibility of chats for that day
            with st.expander(date_label):
                # Sort sessions within each day (newest chat first)
                sorted_sessions_for_day = sorted(sessions_by_date[date_str], reverse=True)
                for session_id in sorted_sessions_for_day:
                    title = st.session_state.bankai_chat_manager.get_session_title(session_id)
                    
                    # Ensure title is a valid string, providing fallbacks
                    if title is None or not str(title).strip():
                        # If no title or empty title, try to use the first message as title
                        session_history_for_title = st.session_state.bankai_chat_manager.get_session_history(session_id)
                        if session_history_for_title and session_history_for_title[0]['text']:
                            title = session_history_for_title[0]['text'][:30] # Use first 30 chars
                            if len(session_history_for_title[0]['text']) > 30:
                                title += "..." # Add ellipsis if truncated
                        else:
                            title = f"Untitled Chat {session_id}" # Final fallback

                    is_current = (session_id == st.session_state.current_chat_session_id)
                    
                    # Display chat title and delete button side-by-side
                    col_title, col_delete = st.columns([0.8, 0.2])
                    with col_title:
                        # Ensure 'title' is always explicitly converted to string for st.button
                        if st.button(str(title), key=f"chat_title_{session_id}", use_container_width=True, type="primary" if is_current else "secondary"):
                            # Save current session's state before loading a new one
                            st.session_state.bankai_chat_manager.set_session_user_info(st.session_state.current_chat_session_id, st.session_state.user_info)
                            st.session_state.bankai_chat_manager.set_session_current_step(st.session_state.current_chat_session_id, st.session_state.current_step)
                            st.session_state.bankai_chat_manager.set_session_account_confirmed(st.session_state.current_chat_session_id, st.session_state.account_confirmed)

                            # Load the selected session's state and history
                            st.session_state.current_chat_session_id = session_id
                            st.session_state.bankai_chat_manager.get_session(session_id) # Re-initialize the chat session with its history
                            st.session_state.user_info = st.session_state.bankai_chat_manager.get_session_user_info(session_id)
                            st.session_state.current_step = st.session_state.bankai_chat_manager.get_session_current_step(session_id)
                            st.session_state.account_confirmed = st.session_state.bankai_chat_manager.get_session_account_confirmed(session_id)
                            st.session_state.conversation_started_in_current_session = True # Mark as started as it's an existing chat
                            st.rerun() # Rerun to display the selected chat

                    with col_delete:
                        # Delete button for each chat history item
                        if st.button("🗑️", key=f"delete_chat_{session_id}", help="Delete chat history"):
                            st.session_state.bankai_chat_manager.delete_session(session_id)
                            # If the deleted session was the current one, switch to a new chat
                            if st.session_state.current_chat_session_id == session_id:
                                new_session_id = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
                                st.session_state.current_chat_session_id = new_session_id
                                st.session_state.bankai_chat_manager.get_session(new_session_id)
                                st.session_state.user_info = {}
                                st.session_state.current_step = "welcome"
                                st.session_state.account_confirmed = False
                                st.session_state.conversation_started_in_current_session = False
                            st.rerun() # Rerun to update the sidebar and main chat area

    st.markdown("---")


# --- Main Chat Area Display ---

# Get the history for the currently active session
current_session_history = st.session_state.bankai_chat_manager.get_session_history(
    st.session_state.current_chat_session_id
)

# Display initial greeting if it's a truly new session (no history yet)
if not current_session_history and not st.session_state.conversation_started_in_current_session:
    initial_greeting = "Hello! I'm Bankai, your virtual assistant for Cooperative Bank of Oromia. How can I assist you today?"
    st.write(initial_greeting)
    add_message_to_current_session("Bankai", initial_greeting)
    st.session_state.conversation_started_in_current_session = True # Mark as started after greeting

# Iterate through the history and display each message
for message in current_session_history:
    with st.chat_message(message["role"]):
        st.markdown(message["text"])


# --- Conversation Flow Logic & User Input ---

# Main chat input field for user queries
user_prompt = st.chat_input("Type your message here...", key="main_chat_input")

if user_prompt:
    add_message_to_current_session("You", user_prompt) # Add user's message to history
    st.rerun() # Rerun immediately to display the user's message

# This block executes AFTER the rerun to handle the bot's response
if user_prompt: # Check if user_prompt still exists after rerun
    response_from_bankai = ""
    with st.spinner("Bankai is typing..."): # Show spinner while waiting for response
        # Determine the bot's response based on the current step and user input
        if not st.session_state.user_info and not st.session_state.account_confirmed:
            if st.session_state.current_step == "welcome":
                # Check for explicit account opening intent
                if "open an account" in user_prompt.lower() or "new account" in user_prompt.lower() or "create account" in user_prompt.lower():
                    response_from_bankai = st.session_state.bankai_chat_manager.send_message_in_session(
                        st.session_state.current_chat_session_id, "user wants to open an account"
                    )
                    st.session_state.current_step = "get_name" # Advance step
                else: # General query during welcome phase
                    response_from_bankai = st.session_state.bankai_chat_manager.send_message_in_session(
                        st.session_state.current_chat_session_id, user_prompt
                    )
                    
        elif st.session_state.current_step in ["get_name", "get_dob", "get_address", "upload_id_front", "upload_id_back", "confirm_info"]:
            # If user types in chat during a specific form flow, treat as a general query
            # (unless it's a form submission handled by specific buttons below)
            response_from_bankai = st.session_state.bankai_chat_manager.send_message_in_session(
                st.session_state.current_chat_session_id, user_prompt
            )
        
        elif st.session_state.account_confirmed: # After account is confirmed, all queries are general
            response_from_bankai = st.session_state.bankai_chat_manager.send_message_in_session(
                st.session_state.current_chat_session_id, user_prompt
            )
    
    # After receiving the response, add it to history and trigger another rerun
    if response_from_bankai:
        add_message_to_current_session("Bankai", response_from_bankai)
        st.rerun() # Rerun to display bot's response
    else:
        st.warning("Bankai did not generate a response for that query. Please try rephrasing.")
        # No rerun here, let next user interaction or form submission trigger it


# --- Form Inputs for Account Opening Flow (conditionally rendered) ---
# These input fields and buttons are displayed only when `current_step` matches
if st.session_state.current_step == "get_name":
    st.write("Please provide your full legal name.")
    col1, col2, col3 = st.columns(3)
    with col1:
        first_name = st.text_input("First Name", key="fn")
    with col2:
        middle_name = st.text_input("Middle Name (optional)", key="mn")
    with col3:
        last_name = st.text_input("Last Name", key="ln")

    if st.button("Submit Name"):
        if first_name and last_name:
            st.session_state.user_info["first_name"] = first_name
            st.session_state.user_info["middle_name"] = middle_name
            st.session_state.user_info["last_name"] = last_name
            
            user_message = f"My name is {first_name} {middle_name} {last_name}."
            add_message_to_current_session("You", user_message)

            response = st.session_state.bankai_chat_manager.send_message_in_session(
                st.session_state.current_chat_session_id, "User provided name. Next: date of birth."
            )
            add_message_to_current_session("Bankai", response)
            st.session_state.current_step = "get_dob"
            st.rerun()
        else:
            st.error("Please provide at least your First and Last Name.")

elif st.session_state.current_step == "get_dob":
    st.write("What is your Date of Birth?")
    dob = st.text_input("Date of Birth (YYYY-MM-DD)", key="dob")
    if st.button("Submit Date of Birth"):
        if dob:
            st.session_state.user_info["dob"] = dob
            user_message = f"My date of birth is {dob}."
            add_message_to_current_session("You", user_message)

            response = st.session_state.bankai_chat_manager.send_message_in_session(
                st.session_state.current_chat_session_id, "User provided DOB. Next: residential address."
            )
            add_message_to_current_session("Bankai", response)
            st.session_state.current_step = "get_address"
            st.rerun()
        else:
            st.error("Please provide your Date of Birth.")

elif st.session_state.current_step == "get_address":
    st.write("What is your Residential Address?")
    address = st.text_input("Residential Address", key="address")
    if st.button("Submit Address"):
        if address:
            st.session_state.user_info["address"] = address
            user_message = f"My address is {address}."
            add_message_to_current_session("You", user_message)

            response = st.session_state.bankai_chat_manager.send_message_in_session(
                st.session_state.current_chat_session_id, "User provided address. Next: upload ID."
            )
            add_message_to_current_session("Bankai", response)
            st.session_state.current_step = "upload_id_front"
            st.rerun()
        else:
            st.error("Please provide your Residential Address.")

elif st.session_state.current_step == "upload_id_front":
    st.write("Upload the **front side** of your ID for verification.")
    uploaded_file_front = st.file_uploader(
        "Upload ID Front (Your data is secure)",
        type=["jpg", "jpeg", "png"],
        key="id_uploader_front"
    )
    if uploaded_file_front:
        # st.image(uploaded_file_front, caption="Uploaded ID Front.", use_column_width=True) # Display uploaded image
        st.session_state.user_info["id_front"] = "uploaded" # Store a flag that it's uploaded
        id_message_front = "I have uploaded the front side of my ID."
        
        add_message_to_current_session("You", id_message_front)

        response_text = st.session_state.bankai_chat_manager.send_message_in_session(
            st.session_state.current_chat_session_id, "User uploaded ID front. Now ask for back."
        )
        add_message_to_current_session("Bankai", response_text)
        st.session_state.current_step = "upload_id_back"
        st.rerun()

elif st.session_state.current_step == "upload_id_back":
    st.write("Now, please upload the **back side** of your ID.")
    uploaded_file_back = st.file_uploader(
        "Upload ID Back (Your data is secure)",
        type=["jpg", "jpeg", "png"],
        key="id_uploader_back"
    )
    if uploaded_file_back:
        # st.image(uploaded_file_back, caption="Uploaded ID Back.", use_column_width=True) # Display uploaded image
        st.session_state.user_info["id_back"] = "uploaded" # Store a flag that it's uploaded
        id_message_back = "I have uploaded the back side of my ID."
        
        add_message_to_current_session("You", id_message_back)

        with st.spinner("Bankai is verifying your ID..."):
            response_text = st.session_state.bankai_chat_manager.send_message_in_session(
                st.session_state.current_chat_session_id, "User uploaded both sides of ID. Confirm details."
            )
            add_message_to_current_session("Bankai", response_text)

        st.session_state.current_step = "confirm_info"
        st.rerun()

elif st.session_state.current_step == "confirm_info" and not st.session_state.account_confirmed:
    st.subheader("Please review your information:")
    user_info = st.session_state.user_info
    st.write(f"**Full Name:** {user_info.get('first_name', '')} {user_info.get('middle_name', '')} {user_info.get('last_name', '')}")
    st.write(f"**Date of Birth:** {user_info.get('dob', '')}")
    st.write(f"**Residential Address:** {user_info.get('address', '')}")
    
    col_confirm, col_edit = st.columns(2)
    with col_confirm:
        if st.button("Confirm Information"):
            account_number = st.session_state.user_db.add_user(
                user_info.get('first_name', ''),
                user_info.get('middle_name', ''),
                user_info.get('last_name', ''),
                user_info.get('dob', ''),
                user_info.get('address', '')
            )
            if account_number:
                st.session_state.user_info["account_number"] = account_number
                confirmation_message = f"Excellent! Your account has been successfully created. Your new account number is **{account_number}**. Welcome to Cooperative Bank of Oromia!"
                st.success(confirmation_message)
                add_message_to_current_session("Bankai", confirmation_message)
                st.session_state.account_confirmed = True
                st.session_state.current_step = "account_created"
                
                # Update persistent session data
                st.session_state.bankai_chat_manager.mark_session_account_created(st.session_state.current_chat_session_id)
                st.session_state.bankai_chat_manager.set_session_user_info(st.session_state.current_chat_session_id, st.session_state.user_info)
                st.session_state.bankai_chat_manager.set_session_current_step(st.session_state.current_chat_session_id, "account_created")
                st.session_state.bankai_chat_manager.set_session_account_confirmed(st.session_state.current_chat_session_id, True)
                st.rerun()

            else:
                st.error("There was an issue creating your account, or an account with this name already exists. Please try again or contact support.")
                add_message_to_current_session("Bankai", "Account creation failed.")

    with col_edit:
        if st.button("Edit Information"):
            st.session_state.current_step = "get_name" # Go back to the first step of data collection
            st.session_state.user_info = {} # Clear user info to restart collection
            st.warning("Please re-enter your information from the beginning.")
            # Also reset session state in manager
            st.session_state.bankai_chat_manager.set_session_user_info(st.session_state.current_chat_session_id, {})
            st.session_state.bankai_chat_manager.set_session_current_step(st.session_state.current_chat_session_id, "get_name")
            st.session_state.bankai_chat_manager.set_session_account_confirmed(st.session_state.current_chat_session_id, False)
            st.rerun()

# This part ensures that the current session's UI state is saved back into the
# `bankai_chat_manager`'s internal memory (which then persists to JSON).
# This is crucial for maintaining context when switching between chats or restarting the app.
st.session_state.bankai_chat_manager.set_session_user_info(st.session_state.current_chat_session_id, st.session_state.user_info)
st.session_state.bankai_chat_manager.set_session_current_step(st.session_state.current_chat_session_id, st.session_state.current_step)
st.session_state.bankai_chat_manager.set_session_account_confirmed(st.session_state.current_chat_session_id, st.session_state.account_confirmed)