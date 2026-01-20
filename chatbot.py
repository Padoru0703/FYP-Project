from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import time
import markdown
import uuid
import spacy
import re
from scraper_module import scrape_shopee_price
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate

nlp = spacy.load("en_core_web_sm")

def extract_component_name(text):
    text = text.lower()

    # Match GPU models like RTX 4060 Ti, RX 6600 XT
    gpu_match = re.search(r"(rtx\s*\d{3,4}\s*ti?|gtx\s*\d{3,4}|rx\s*\d{3,4}\s*xt?)", text)
    if gpu_match:
        return gpu_match.group(0).replace(" ", "")

    # Match CPU models like Ryzen 5 5600G or i5-12400F
    cpu_match = re.search(r"(ryzen\s*\d\s*\d{4}[a-z]*|i[3579]-\d{4,5}[a-z]*)", text)
    if cpu_match:
        return cpu_match.group(0).replace(" ", "")

    # Match generic fallback keywords
    for word in ["gpu", "cpu", "ssd", "ram", "hdd", "psu", "motherboard", "cooler"]:
        if word in text:
            return word

    return None


app = Flask(__name__)
app.secret_key = "secretkey"  

video_links = [
    {
        "keywords": ["build a pc", "how to build a pc", "assemble pc", "build computer", "Guide me through the assembly process"],
        "link": "https://www.youtube.com/watch?v=PXaLc9AYIcg"
    }
]

def get_video_link(user_input):
    user_input = user_input.lower()
    for video in video_links:
        for keyword in video["keywords"]:
            if keyword in user_input:
                return f"📺 Here's a helpful video on how to {keyword}:\n{video['link']}"
    return None

# Initialize database for user accounts
def init_db():
    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message TEXT NOT NULL,
                sender TEXT NOT NULL,  -- 'user' or 'bot'
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

init_db()

data_store = []

# Initialize chatbot model
template = """
You are PCGenie, an AI assistant that helps users build and compare PC components.

Answer the question below in a structured format.

Here is the conversation history: 
{context}

Question: {question}

Answer (use bullet points if listing items):

Use RM for the currency code
"""
model = OllamaLLM(model="llama3", stream=True)
prompt = ChatPromptTemplate.from_template(template)
chain = prompt | model

# Home route (Requires login)
@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user" in session:
        username = "Guest" if session.get("guest") else session["user"]
        return render_template("index.html", username=username)
    return redirect(url_for("login"))

# Register route
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Handle both form data and JSON data
        if request.content_type == "application/json":
            data = request.get_json()
            username = data.get("username")
            password = generate_password_hash(data.get("password"))
        else:
            username = request.form["username"]
            password = generate_password_hash(request.form["password"])

        with sqlite3.connect("users.db") as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                session["user"] = username
                if request.content_type == "application/json":
                    return jsonify({"success": True, "redirect": "/login"}), 200
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                if request.content_type == "application/json":
                    return jsonify({"success": False, "message": "Username already exists!"}), 400
                return "Username already exists! Try another one."

    return render_template("register.html")


# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Check if request is JSON (fetch API)
        if request.content_type == "application/json":
            data = request.get_json()
            username = data.get("username")
            password = data.get("password")
        else:  # Handle regular form submission
            username = request.form.get("username")
            password = request.form.get("password")

        with sqlite3.connect("users.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()

            if user and check_password_hash(user[0], password):
                session["user"] = username
                if request.content_type == "application/json":
                    return jsonify({"success": True, "redirect": "/"}), 200  # Response for fetch API
                return redirect(url_for("home"))  # Redirect for form submission

        if request.content_type == "application/json":
            return jsonify({"success": False, "message": "Invalid credentials"}), 401
        return "Invalid credentials. Try again!", 401

    return render_template("login.html")


@app.route("/guest-login", methods=["POST"])
def guest_login():
    guest_id = str(uuid.uuid4())[:8]  # Generate short random guest ID
    session["user"] = f"guest_{guest_id}"
    session["guest"] = True  # Mark this session as guest
    return jsonify({"success": True})


# Logout route
@app.route("/logout",methods=["POST"])
def logout():
    session.pop("user", None)
    session.pop("chat_id", None)
    session.clear()  # Clear session data
    return jsonify({"success": True})

# Password Reset Route
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        data = request.get_json()
        username = data.get("username")
        new_password = generate_password_hash(data.get("newPassword"))

        with sqlite3.connect("users.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()

            if user:
                cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, username))
                conn.commit()
                return jsonify({"success": True, "message": "✅ Password reset successful! Redirecting to login..."}), 200
            else:
                return jsonify({"success": False, "message": "❌ Username not found!"}), 404

    return render_template("reset_password.html")

# Chatbot page (Requires login)
@app.route("/chat", methods=["POST", "GET"])
def handle_conversation():
    if "user" not in session:
        return redirect(url_for("login"))

    if not request.json or "text" not in request.json:
        return jsonify({"error": "Invalid request"}), 400

    user = session["user"]
    text = request.json["text"]
    chat_id = session.get("chat_id") # Retrieve chat_id from session

    if not chat_id:
        chat_id = str(uuid.uuid4())  # Generate a new unique chat ID
        session["chat_id"] = chat_id  # Store in session

    # Store user message in the database
    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO history (user, chat_id, message, sender) VALUES (?, ?, ?, ?)", 
                       (user, chat_id, text, "user"))
        conn.commit()

    
    response_generator = stream_chat(text, chat_id)

    # Store streamed content as we yield it
    def generate_and_store():
        bot_response = ""
        for word in response_generator:
            bot_response += word
            yield word
        # After full response is streamed, save to DB
        with sqlite3.connect("users.db") as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO history (user, chat_id, message, sender) VALUES (?, ?, ?, ?)", 
                        (user, chat_id, bot_response.strip(), "bot"))
            conn.commit()

    return Response(generate_and_store(), mimetype='text/plain')

def summarize_history(chat_id):
    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sender, message FROM history 
            WHERE chat_id = ? 
            ORDER BY id ASC
        """, (chat_id,))
        rows = cursor.fetchall()

    full_context = ""
    for sender, message in rows:
        label = "User" if sender == "user" else "PCGenie"
        full_context += f"{label}: {message}\n"

    # Ask the LLM to summarize
    summary_prompt = f"""
    Summarize the following conversation in a few bullet points to retain the important context for a PC-building chatbot:

    {full_context}
    """

    summary = chain.invoke({"context": "", "question": summary_prompt})
    return summary.strip()

# Chatbot streaming response
def stream_chat(text, chat_id):
    print("Generating response...")

    # Get all messages
    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sender, message FROM history 
            WHERE chat_id = ? 
            ORDER BY id ASC
        """, (chat_id,))
        rows = cursor.fetchall()

    summarized_context = ""
    
    if len(rows) > 12:  # if too many messages, summarize older ones
        old_history = rows[:-6]
        recent_history = rows[-6:]

        # Summarize old history
        old_context = ""
        for sender, message in old_history:
            label = "User" if sender == "user" else "PCGenie"
            old_context += f"{label}: {message}\n"

        summary_prompt = f"""
        Summarize this conversation for memory retention:

        {old_context}
        """

        summary = chain.invoke({"context": "", "question": summary_prompt})
        summarized_context = f"[Earlier Summary]\n{summary.strip()}\n"
    else:
        recent_history = rows  # <-- FIX: define recent_history for short chats

    # Format recent history
    recent_context = ""
    for sender, message in recent_history:
        label = "User" if sender == "user" else "PCGenie"
        recent_context += f"{label}: {message}\n"

    full_context = summarized_context + recent_context
    
    # Ask the model with summarized + recent context
    response = chain.invoke({"context": full_context.strip(), "question": text})

    # Check for helpful video
    video_suggestion = get_video_link(text)
    if video_suggestion:
        url_match = re.search(r"(https?://[^\s]+)", video_suggestion)
        if url_match:
            youtube_url = url_match.group(1)
            video_link = f"[Watch this tutorial]({youtube_url})"
            response += f"\n\n{video_link}"

    formatted_response = markdown.markdown(response)

    words = formatted_response.split()
    for word in words:
        yield word + " "
        time.sleep(0.05)



@app.route("/chat-history", methods=["GET"])
def get_chat_history():
    if "user" not in session:
        return redirect(url_for("login"))
    
    if session.get("guest"):
        return jsonify([])  # Guests have no saved history

    user = session["user"]
    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT chat_id FROM history WHERE user = ? ORDER BY timestamp DESC", (user,))
        chats = [row[0] for row in cursor.fetchall()]

    return jsonify(chats)

@app.route("/chat-history/<chat_id>", methods=["GET"])
def get_chat_messages(chat_id):
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    session["chat_id"] = chat_id 
    
    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT message, sender FROM history WHERE user = ? AND chat_id = ? ORDER BY timestamp", (user, chat_id))
        messages = [{"message": row[0], "sender": row[1]} for row in cursor.fetchall()]

    return jsonify(messages)

@app.route("/new-chat", methods=["POST"])
def new_chat():
    if "user" not in session:
        return redirect(url_for("login"))
    
    welcome_message = (
        "👋 Hello there! Welcome to PCGenie, your smart assistant for building the perfect PC.<br>"
        "I can help you:<ul>"
        "<li>⚡ Compare components</li>"
        "<li>🔧 Suggest builds based on your needs</li>"
        "<li>🛠️ Guide you through the assembly process</li>"
        "</ul>"
        "What are you looking to do today? 🤔"
    )
    
    if session.get("guest"):  # Guest user
        new_chat_id = str(uuid.uuid4())
        session["chat_id"] = new_chat_id
        return jsonify({"chat_id": new_chat_id})

    user = session["user"]
    new_chat_id = str(uuid.uuid4())

    # Ensure previous chat_id is removed before setting a new one
    session.pop("chat_id", None)  
    session["chat_id"] = new_chat_id

    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO history (chat_id, user, message, sender, timestamp) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                       (new_chat_id, user, welcome_message, "bot"))
        conn.commit()

    return jsonify({"chat_id": new_chat_id})

@app.route("/delete-chat/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    user = session["user"]
    
    with sqlite3.connect("users.db") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history WHERE user = ? AND chat_id = ?", (user, chat_id))
        conn.commit()

    return jsonify({"success": True, "message": "Chat deleted successfully"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
