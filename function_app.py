import azure.functions as func
import logging
import os
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from telebot import TeleBot
import json
from openai import AzureOpenAI


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS)
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    # Get the bot token from environment variables
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    # Check if the request method is POST
    if req.method == 'POST':    
        # Get the JSON content of the request
        update = req.get_json()

        try:
            # Check if the update contains a message
            if update['message']:
                # Extract the username, user id, and chat id from the message
                username = update['message']['from']['first_name']
                user_id = update['message']['from']['id']
                chat_id = update['message']['chat']['id']

                # Create a file prefix using the username and user id
                fileprefix = f'{username}_{user_id}'

                # Log the received message
                logging.log(logging.INFO, f'User {username} with id {user_id} sent a message: {update["message"]["text"]}')

                # Get the Azure storage connection string from environment variables
                connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

                # Initialize the BlobServiceClient
                blob_service_client = BlobServiceClient.from_connection_string(conn_str=connection_string)

                # Get the blob client for the specific blob
                blob_client = blob_service_client.get_blob_client("history", f'{fileprefix}_history.txt')
                
                # Call the message_next function to process the message
                message_next(chat_id, bot_token, update['message']['text'], fileprefix, blob_client)

                # Return a 200 OK response
                return func.HttpResponse(status_code=200)

        except Exception as e:
            # Log any exceptions that occur
            logging.error(f'Oops, we got an exception in http_trigger: {e}')

            # Return a 200 OK response
            return func.HttpResponse(status_code=200)

    else:
        # If the request method is not POST, return a 200 OK response with a message
        return func.HttpResponse("This is a bot server.", status_code=200)

def message_next(chat_id, bot_token, text, fileprefix, blob_client):
    # Initialize the bot
    bot = TeleBot(bot_token)
    
    # Initialize the conversation and query
    conversation = []
    query = []

    # Check if the blob exists
    if blob_client.exists():
        # If the text is '/startover', delete the blob and start over
        if text == '/startover':
            blob_client.delete_blob()
            bot.send_message(chat_id, "Okay, let's start over")
            logging.info(f'{fileprefix}_history.txt deleted')
            return func.HttpResponse("This is a bot server.", status_code=200)
        else:
            # Download the blob and split it into lines
            conversation = blob_client.download_blob().readall().decode('utf-8')
            lines = conversation.split('\n')
            conversation = [json.loads(line) for line in lines]

            # Check if the previous user input is the same as the current one
            if conversation[-2]["content"] == text:
                logging.warn('The text is the same as the previous user content in the history file')
                return func.HttpResponse(status_code=200)

    # Append the user's text to the conversation
    conversation.append({"role": "user", "content": text})
    conversation = conversation[-4:]

    # Read the prompt from the file and add it to the query
    with open(f'prompt_english.txt', 'r') as f:
        query = [{"role": "system", "content": f.read().strip()}]
        query.extend(conversation)

    # Get the response from the AI model
    response = get_response(query)

    # Send the response to the user
    # Log the response message
    logging.log(logging.INFO, f'Response: {response}')
    bot.send_message(chat_id, response, parse_mode="Markdown")

    # Append the assistant's response to the conversation
    conversation.append({"role": "assistant", "content": response})

    # Convert the conversation to JSON and upload it to the blob
    conversation = [json.dumps(message) for message in conversation]
    conversation = "\n".join(conversation)
    blob_client.upload_blob(conversation, overwrite=True)

def get_response(conversation):
    """
    This function is used to get a response from Azure OpenAI.
    It takes a conversation as input and returns the response from the AI model.

    Parameters:
    conversation (list): A list of conversation history.

    Returns:
    text (str): The response from the AI model.
    """

    # Initialize the AzureOpenAI client
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_KEY"),  
        api_version="2023-09-15-preview",
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )

    # Create a chat completion using the AzureOpenAI client
    response = client.chat.completions.create(
        model="gpt-4",
        messages=conversation,
    )
    
    # Extract the content from the response
    text = response.choices[0].message.content

    return text
