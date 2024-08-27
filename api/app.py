import os
import json
import requests
import boto3
from pinecone.grpc import PineconeGRPC as Pinecone

ACCESS_TOKEN = os.getenv('WHATSAPP_TOKEN')
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')

def getContext(query, phone_number_id):
    try:
        # Initialize Pinecone client
        pc = Pinecone(api_key=PINECONE_API_KEY)
        
        # Embed the query
        embedding_result = pc.inference.embed(
            "multilingual-e5-large",
            inputs=[query],
            parameters={"input_type": "query"}
        )
    except Exception as e:
        return 500, {'error': 'Embedding Generation Failed', 'details': str(e)}
    
    try:
        # Retrieve the index
        index = pc.Index('serverless-index-1')
    except Exception as e:
        return 500, {'error': 'Index Retrieval Failed', 'details': str(e)}
    
    try:
        # Query the index with the generated embedding
        results = index.query(
            namespace=phone_number_id,
            vector=embedding_result[0].values,
            top_k=3,
            include_values=False,
            include_metadata=True
        )
        
        if results.matches and len(results.matches) > 0:
            return 200, {'context': results.matches[0].metadata['text']}
        else:
            return 404, {'error': 'No matches found'}
    
    except Exception as e:
        return 500, {'error': 'Matching Failed', 'details': str(e)}

def prepare_prompt(question, context_text):
    return f"Human: You're an LLM For a RAG App. I will give you context and a question. Provide an answer using only the content provided. Apologize if you cannot find an answer in the context.\nContext: \"{context_text}\" \nQuestion: {question}\nAssistant:"

def invoke_bedrock_model(prompt):
    body_dict = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    }

    body_json = json.dumps(body_dict)
    body_bytes = body_json.encode('utf-8')

    try:
        # session = boto3.session.Session()
        bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

        response = bedrock.invoke_model(
            modelId="anthropic.claude-3-sonnet-20240229-v1:0",
            contentType="application/json",
            accept="application/json",
            body=body_bytes
        )

        reply = json.loads(response['body'].read())
        return {'statusCode': 200, 'response': reply}

    except boto3.exceptions.Boto3Error as e:
        print("Boto3 error:", e)
        return {'statusCode': 500, 'error': 'Boto3 error occurred', 'details': str(e)}

    except json.JSONDecodeError as e:
        print("JSON decode error:", e)
        return {'statusCode': 500, 'error': 'JSON decode error occurred', 'details': str(e)}

    except Exception as e:
        print("Unexpected error:", e)
        return {'statusCode': 500, 'error': 'Unexpected error occurred', 'details': str(e)}

def lambda_handler(event, context):
    print("Function Invoked")

    try:
        query_params = event.get('queryStringParameters')

        if query_params is not None:
            verify_token = VERIFY_TOKEN
            mode = query_params.get('hub.mode')
            token = query_params.get('hub.verify_token')
            challenge = query_params.get('hub.challenge')

            if mode and token:
                if mode == "subscribe" and token == verify_token:
                    print("WEBHOOK_VERIFIED")
                    return {
                        'statusCode': 200,
                        'body': challenge
                    }
                else:
                    return {
                        'statusCode': 403
                    }
        else:
            token = ACCESS_TOKEN
            body = json.loads(event['body'])
            if body.get('object'):
                if (
                    body['entry'] and
                    body['entry'][0]['changes'] and
                    body['entry'][0]['changes'][0]['value'].get('messages') and
                    body['entry'][0]['changes'][0]['value']['messages'][0]
                ):
                    phone_number_id = body['entry'][0]['changes'][0]['value']['metadata']['phone_number_id']
                    from_ = body['entry'][0]['changes'][0]['value']['messages'][0]['from']
                    #Check if type is 'voice' 
                    msg_body = body['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']
                    
                    if not from_ or not msg_body:
                        return {
                            'statusCode': 400,
                            'body': json.dumps({'error': 'Invalid message payload'})
                        }
                    
                    print(f"Received message from {from_}: {msg_body}")

                    status_code, response = getContext(msg_body, 'ns1')
                    if status_code != 200:
                        return {
                            'statusCode': status_code,
                            'body': json.dumps(response)
                        }
                    
                    context_text = response['context']
                    print(f"Context for message: {context_text}")

                    prompt = prepare_prompt(question=msg_body, context_text=context_text)
                    result = invoke_bedrock_model(prompt)
                    if result['statusCode'] != 200:
                        return {
                            'statusCode': result['statusCode'],
                            'body': json.dumps(result)
                        }
                    responseText = result['response']
                    reply = responseText['content'][0]['text'] if 'content' in responseText and len(responseText['content']) > 0 else "I'm sorry this document doesn't contain information regarding this."

                    try:
                        response = requests.post(
                            f"https://graph.facebook.com/v12.0/{phone_number_id}/messages?access_token={token}",
                            json={
                                'messaging_product': 'whatsapp',
                                'to': from_,
                                'text': {'body': reply},
                            },
                            headers={'Content-Type': 'application/json'}
                        )
                        response.raise_for_status()
                    except requests.exceptions.RequestException as error:
                        print("Error sending message:", error)
                        return {
                            'statusCode': 500,
                            'body': json.dumps({'error': 'Failed to send message.'})
                        }

                    return {
                        'statusCode': 200
                    }

    except Exception as e:
        print("Unexpected error in lambda_handler:", e)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal Server Error', 'details': str(e)})
        }


#Before Code review

# import os
# import json
# import requests
# from pinecone.grpc import PineconeGRPC as Pinecone
# from pinecone import ServerlessSpec
# from pinecone.grpc import PineconeGRPC
# import boto3


# ACCESS_TOKEN = os.getenv('WHATSAPP_TOKEN')
# PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
# VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')

# def getContext(query, phone_number_id):
#     try:
#         # Initialize Pinecone client
#         pc = Pinecone(api_key=PINECONE_API_KEY)
        
#         # Embed the query
#         embedding_result = pc.inference.embed(
#             "multilingual-e5-large",
#             inputs=[query],
#             parameters={"input_type": "query"}
#         )
#     except Exception as e:
#         return 500, {'error': 'Embedding Generation Failed', 'details': str(e)}
    
#     try:
#         # Retrieve the index
#         index = pc.Index('serverless-index-1')
#     except Exception as e:
#         return 500, {'error': 'Index Retrieval Failed', 'details': str(e)}
    
#     try:
#         # Query the index with the generated embedding
#         results = index.query(
#             namespace=phone_number_id,
#             vector=embedding_result[0].values,
#             top_k=3,
#             include_values=False,
#             include_metadata=True
#         )
        
#         if results.matches and len(results.matches) > 0:
#             return 200, {'context': results.matches[0].metadata['text']}
#         else:
#             return 404, {'error': 'No matches found'}
    
#     except Exception as e:
#         return 500, {'error': 'Matching Failed', 'details': str(e)}
    
# def prepare_prompt(question, context_text):
    
#     return f"Human: You're an LLM For a RAG App, I will give you context and question. You've to give the proper answer using only the content that I give you. Don't make up answers, simply apologize if you can't deduce the answer from the context.\nContext: \"{context_text}\nQuestion:{question}.\nAssistant:"

# def invoke_bedrock_model(prompt):
#     # Prepare the request body
#     body_dict = {
#         "anthropic_version": "bedrock-2023-05-31",
#         "max_tokens": 1000,
#         "messages": [
#             {
#                 "role": "user",
#                 "content": [
#                     {
#                         "type": "text",
#                         "text": prompt
#                     }
#                 ]
#             }
#         ]
#     }

#     # Convert the dictionary to a JSON string and then encode it to bytes
#     body_json = json.dumps(body_dict)
#     body_bytes = body_json.encode('utf-8')

#     try:
#         # Initialize a session and client for AWS Bedrock
#         session = boto3.session.Session()
#         bedrock = session.client('bedrock-runtime', region_name='us-east-1')

#         # Invoke the model
#         response = bedrock.invoke_model(
#             modelId="anthropic.claude-3-sonnet-20240229-v1:0",
#             contentType="application/json",
#             accept="application/json",
#             body=body_bytes
#         )

#         # Parse and return the model's response
#         reply = json.loads(response['body'].read())
#         return {'statusCode': 200, 'response': reply}

#     except boto3.exceptions.Boto3Error as e:
#         # Handle errors related to AWS SDK
#         print("Boto3 error:", e)
#         return {'statusCode': 500, 'error': 'Boto3 error occurred', 'details': str(e)}

#     except json.JSONDecodeError as e:
#         # Handle JSON parsing errors
#         print("JSON decode error:", e)
#         return {'statusCode': 500, 'error': 'JSON decode error occurred', 'details': str(e)}

#     except Exception as e:
#         # Handle other unforeseen errors
#         print("Unexpected error:", e)
#         return {'statusCode': 500, 'error': 'Unexpected error occurred', 'details': str(e)}
    
# def lambda_handler(event, context):
    
#     print("Function Invoked")

#     query_params = event.get('queryStringParameters')

#     if query_params is not None:
#         # Register the webhook
#         verify_token = VERIFY_TOKEN

#         # Parse params from the webhook verification request
#         mode = query_params.get('hub.mode')
#         token = query_params.get('hub.verify_token')
#         challenge = query_params.get('hub.challenge')

#         # Check if a token and mode were sent
#         if mode and token:
#             # Check the mode and token sent are correct
#             if mode == "subscribe" and token == verify_token:
#                 print("WEBHOOK_VERIFIED")
#                 return {
#                     'statusCode': 200,
#                     'body': challenge
#                 }
#             else:
#                 # Responds with '403 Forbidden' if verify tokens do not match
#                 return {
#                     'statusCode': 403
#                 }
#     else:
        
        
#         token = ACCESS_TOKEN
#         body = json.loads(event['body'])
#         if body.get('object'):
#             if (
#                 body['entry'] and
#                 body['entry'][0]['changes'] and
#                 body['entry'][0]['changes'][0]['value'].get('messages') and
#                 body['entry'][0]['changes'][0]['value']['messages'][0]
#             ):
#                 phone_number_id = body['entry'][0]['changes'][0]['value']['metadata']['phone_number_id']
#                 from_ = body['entry'][0]['changes'][0]['value']['messages'][0]['from']  # extract the phone number from the webhook payload
#                 msg_body = body['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']  # extract the message text from the webhook payload
                
#                 if not from_ or not msg_body:
#                     return {
#                         'statusCode': 400,
#                         'body': json.dumps({'error': 'Invalid message payload'})
#                     }
                
#                 print(f"Received message from {from_}: {msg_body}")
                
#                 # ----------------------------------------------------------------------------------------------------------------------------------------
#                 #Handle getting the context from pinecone
#                 status_code, response = getContext(msg_body, 'ns1')
#                 if status_code != 200:
#                     # If getContext returned an error, return the error to the client
#                     return {
#                         'statusCode': status_code,
#                         'body': json.dumps(response)
#                     }
                
#                 # Extract the context from the successful response
#                 context_text = response['context']
#                 print(f"Context for message: {context_text}")
#                 # ----------------------------------------------------------------------------------------------------------------------------------------
#                 #Send the context and the query to the model
#                 prompt = prepare_prompt(question=msg_body, context_text=context_text)
#                 result = invoke_bedrock_model(prompt)
#                 if result['statusCode'] != 200:
#                     return {
#                         'statusCode': result['statusCode'],
#                         'body': json.dumps(result)
#                     }
#                 responseText = result['response']
#                 reply = responseText['content'][0]['text']
                
#                 if not len(reply) > 0:
#                     reply = "We're sorry, there was an error processing your request."
#                 # ----------------------------------------------------------------------------------------------------------------------------------------
#                 # Handle sending the message
#                 try:
#                     response = requests.post(
#                         f"https://graph.facebook.com/v12.0/{phone_number_id}/messages?access_token={token}",
#                         json={
#                             'messaging_product': 'whatsapp',
#                             'to': from_,
#                             'text': {'body': context_text},
#                         },
#                         headers={'Content-Type': 'application/json'}
#                     )
#                     response.raise_for_status()
#                 except requests.exceptions.RequestException as error:
#                     print("Error sending message:", error)
#                     return {
#                         'statusCode': 500,
#                         'body': json.dumps({'error': 'Failed to send message.'})
#                     }

#                 return {
#                     'statusCode': 200
#                 }
