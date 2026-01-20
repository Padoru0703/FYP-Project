import sqlite3

connection = sqlite3.connect('users.db')

connection.execute("DROP TABLE saved_builds")

print("data dropped successfully")

connection.close()