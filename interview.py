import sqlite3

#Connecting to sqlite
conn = sqlite3.connect('users.db')

#Creating a cursor object using the cursor() method
cursor = conn.cursor()

#Doping EMPLOYEE table if already exists
cursor.execute("DROP TABLE chats")
print("Table dropped... ")

#Commit your changes in the database
conn.commit()

#Closing the connection
conn.close()







