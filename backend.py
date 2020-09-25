import requests
import urllib.parse
import json
from flask import Flask, jsonify, request, json
from flask_cors import CORS, cross_origin
import asyncio
import time
import aiohttp
import stripe
import os
import re
from dotenv import load_dotenv
load_dotenv()

import firebase_admin
from firebase_admin import db
from firebase_admin import credentials

cred = credentials.Certificate("adminKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://playlist-search-tool-8b406.firebaseio.com/'
})

# As an admin, the app has access to read and write all data, regradless of Security Rules
# Set your secret key. Remember to switch to your live secret key in production!
# See your keys here: https://dashboard.stripe.com/account/apikeys
stripe.api_key = os.environ.get('STRIPE_API_SK')
endpoint_secret = 'whsec_I9gZa103W2d8RqPZ9d088SacQEcOvTPA'

app = Flask(__name__)
cors = CORS(app)
# CORS(app)

user_info = {}

def batch(iterable, n=1):
  l = len(iterable)
  for ndx in range(0, l, n):
    yield iterable[ndx:min(ndx + n, l)]

def get_key_if_exist(key,dct,default=None):
  if key in dct.keys():
    return dct[key]
  elif default:
    return default
  else:
    return None 

async def get_playlist_details(playlist,access_token):

  # This function gets playlist details for given playlist using
  # asyncio and aiohttp library, headers and payload are passed just like
  # requests libarary.

  # Takes in the whole playlist object and returns the playlist in the end.
  try:
    playlist_id = playlist['id']
    url = "https://api.spotify.com/v1/playlists/"+str(playlist_id)+"?type=track%2Cepisode"
    payload  = {}
    headers = {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer '+str(access_token)
    }
    async with aiohttp.ClientSession() as session:
      async with session.get(url=url,data=payload,headers=headers) as response:
        resp = await response.read()
        followers = json.loads(resp)['followers']['total']
        playlist['followers'] = followers
        return playlist
  except Exception as e:
    print(e)

def find_ig(desc):
  match = re.findall(r'@[^\s]+', desc.lower())
  if match:
    data = []
    for m in match:
      if '.com' not in m and '.edu' not in m and '.net' not in m:
        data.append(m)
    if len(data)==0:
      return None
    return data
  else:
    return None

async def prepare_playlists(playlists,access_token):
  ret = await asyncio.gather(*[get_playlist_details(playlist,access_token) for playlist in playlists])
  print('DONE')
  return ret

def create_offsets(start,total_amount):
  response = []
  if total_amount!=0:
    left = total_amount%50
    for i in range(start,total_amount,50):
      response.append(i) 
    if left!=0:
      response.append(left+response[-1])
  return response

async def get_playlist_async(query,limit,offset,access_token):
  try:
    query = urllib.parse.quote(str(query))
    url = "https://api.spotify.com/v1/search?query="+query+"&type=playlist&include_external=audio&offset="+str(offset)+"&limit="+str(limit)
    payload  = {}
    headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer '+str(access_token),
    "accept": "application/json",
    "accept-language": "en",
    "app-platform": "WebPlayer"
    }
    async with aiohttp.ClientSession() as session:
      async with session.get(url=url,data=payload,headers=headers) as response:
        resp = await response.read()
        resp_as_dict = json.loads(resp)
        if 'error' in resp_as_dict.keys():
          return None
        return json.loads(resp)['playlists']['items']
  except Exception as e:
    print(e)


def get_total_amount(query,access_token):
  total_amount = get_playlist(query,0,50,access_token)['playlists']['total']
  if total_amount>3000:
    total_amount = 3000
  return total_amount

async def collect_playlist(query,access_token,amount,offset):
  print(offset)
  offsets = create_offsets(offset,offset+amount)
  print(offsets)
  ret = await asyncio.gather(*[get_playlist_async(query,50,offset,access_token) for offset in offsets])
  return ret

# This function only used when we don't want to process large data concurrently,
# such as getting total amount of playlists.
def get_playlist(query,offset,limit,access_token):
  
  query = urllib.parse.quote(str(query))
  url = "https://api.spotify.com/v1/search?query="+query+"&type=playlist&include_external=audio&offset="+str(offset)+"&limit="+str(limit)

  payload  = {}
  headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer '+str(access_token),
    "accept": "application/json",
    "accept-language": "en",
    "app-platform": "WebPlayer"
  }
  response = requests.request("GET", url, headers=headers, data = payload)

  return json.loads(response.text.encode('utf8'))

def get_access_token():
  url = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"

  payload = {}
  headers = {}

  response = requests.request("GET", url, headers=headers, data = payload)

  return json.loads(response.text.encode('utf8'))

def filter_playlist(playlist):
  if playlist==None:
    return None
  match = re.search(r'[\w\.-]+@[\w\.-]+', playlist['description'])
  if match:
    mail = match.group()
  else:
    mail = None
  instagram = find_ig(playlist['description'])
  dct={'followers':playlist['followers'],
  'owner':playlist['owner']['display_name'],
  'instagram':instagram,
  'url':playlist['external_urls']['spotify'],
  'name':playlist['name'],
  'mail':mail
  }
  return dct

def handle_checkout_session(session,user_id):
  print(user_id)
  user_ref = db.reference('/users/'+str(user_id))
  user_ref.update({
    "sub_id":session.subscription
  })

@app.route('/get_playlists',methods=['POST'])
@cross_origin()
def f1():
  data = request.get_json()
  query = get_key_if_exist('query',data)
  access_token = get_key_if_exist('access_token',data)
  amount = get_key_if_exist('amount',data)
  offset = get_key_if_exist('offset',data)
  try:
    print('amount:',amount)
    print('offset',offset)
    print('query',query)
    print('token',access_token)
    resp = asyncio.run(collect_playlist(query,access_token,amount,offset))
    print('okayy')
    resp = list(filter(None, resp)) 
    # Everytime an async function is called it returns a list of playlist items,
    # so the list we get here has list inside, we only need playlist items.
    only_playlists = [el for r in resp for el in r]
    print('probly here')
    playlists = [ply for chunk in batch(only_playlists,300) for ply in asyncio.run(prepare_playlists(chunk,access_token))]
    print('lets go')
    data = [filter_playlist(ply) for ply in playlists]
    data = list(filter(None,data))
    print('finished getting data')
    return {'data':data}
  except Exception as e:
    print(e)
    resp = {'error':'couldnt retrieve playlists'}
  return resp

@app.route('/get_total_amount',methods=['POST'])
@cross_origin()
def f3():
  data = request.get_json()
  query = get_key_if_exist('query',data)
  access_token = get_key_if_exist('access_token',data)
  try:
    total_amount = get_total_amount(query,access_token)
    return jsonify(total_amount=total_amount),200
  except Exception as e:
    print(e)
    return jsonify(error=str(e)),500
  return jsonify(error='some error'),500

@app.route('/get_access_token',methods=['POST'])
@cross_origin()
def f2():
  try:
    resp = get_access_token()
  except Exception as e:
    print(e)
    resp = {'error':'couldnt retrieve access token'}
  return resp

@app.route('/create-customer', methods=['POST'])
@cross_origin()
def create_customer():
    # Reads application/json and returns a response
    data = json.loads(request.data)
    try:
        # Create a new customer object
        customer = stripe.Customer.create(
            email=data['email']
        )

        # Recommendation: save the customer.id in your database.

        return jsonify(
            customer=customer
        )
    except Exception as e:
        return jsonify(error=str(e)), 403

@app.route('/sub', methods=['POST'])
@cross_origin()
def sub():
    email = request.json.get('email', None)
    payment_method = request.json.get('payment_method', None)

    if not email:
        return 'You need to send an Email!', 400
    if not payment_method:
        return 'You need to send an payment_method!', 400

    # This creates a new Customer and attaches the default PaymentMethod in one API call.
    customer = stripe.Customer.create(
        payment_method=payment_method,
        email=email,
        invoice_settings={
            'default_payment_method': payment_method,
        },
    )
    # Creates a subscription and attaches the customer to it
    subscription = stripe.Subscription.create(
        customer=customer['id'],
        items=[
            {
                'plan': os.environ.get('STRIPE_PRICE_ID'),
                # 'plan': 'price_1HU1BZCEx2VWspbzLKRovldw',
            },
        ],
        expand=['latest_invoice.payment_intent'],
    )

    status = subscription['latest_invoice']['payment_intent']['status'] 
    client_secret = subscription['latest_invoice']['payment_intent']['client_secret']

    user_info['customer_id'] = customer['id']
    user_info['email'] = email
    
    return {'status': status, 'client_secret': client_secret, 'sub_id': subscription.id}, 200
# @app.route('/create-subscription', methods=['POST'])
# @cross_origin()
# def createSubscription():
#   data = json.loads(request.data)
#   try:
#     # Attach the payment method to the customer
#     stripe.PaymentMethod.attach(
#       data['paymentMethodId'],
#       customer=data['customerId'],
#     )
#     # Set the default payment method on the customer
#     stripe.Customer.modify(
#       data['customerId'],
#       invoice_settings={
#           'default_payment_method': data['paymentMethodId'],
#       },
#     )
#     # Create the subscription
#     subscription = stripe.Subscription.create(
#       customer=data['customerId'],
#       items=[
#           {
#               'price': os.environ.get('STRIPE_PRICE_ID')
#           }
#       ],
#       expand=['latest_invoice.payment_intent'],
#     )
#     print(subscription)
#     return jsonify(subscription)
#   except Exception as e:
#     return jsonify(error={'message': str(e)}), 200

@app.route('/retry-invoice', methods=['POST'])
@cross_origin()
def retrySubscription():
  data = json.loads(request.data)
  try:
    stripe.PaymentMethod.attach(
      data['paymentMethodId'],
      customer=data['customerId'],
    )
    # Set the default payment method on the customer
    stripe.Customer.modify(
      data['customerId'],
      invoice_settings={
          'default_payment_method': data['paymentMethodId'],
      },
    )
    invoice = stripe.Invoice.retrieve(
      data['invoiceId'],
      expand=['payment_intent'],
    )
    print(invoice)
    return jsonify(invoice)
  except Exception as e:
    return jsonify(error={'message': str(e)}), 200

@app.route('/cancel-subscription', methods=['POST'])
@cross_origin()
def cancelSubscription():
  data = json.loads(request.data)
  try:
    # Cancel the subscription by deleting it
    deletedSubscription = stripe.Subscription.delete(data['subscriptionId'])
    return jsonify(deletedSubscription)
  except Exception as e:
    return jsonify(error=str(e)), 403

@app.route('/sub_details', methods=['POST'])
@cross_origin()
def get_sub_details():
  data = json.loads(request.data)
  sub_id = get_key_if_exist('sub_id',data)
  try:
    sub = stripe.Subscription.retrieve(sub_id)
    return sub
  except Exception as e:
    print(e)
    return jsonify(error=str(e)), 403

@app.route('/get_price', methods=['GET'])
@cross_origin()
def get_product_price():
  if os.environ.get('STRIPE_PRICE_ID'):
    price_id = os.environ.get('STRIPE_PRICE_ID')
  else:
    price_id = 'price_HOP48uU0uKCeWE'
  try:
    resp = stripe.Price.retrieve(price_id)
    print(resp)
    if resp['currency']=='usd':
      return {'price':str(float(resp['unit_amount']/100)) + '$'}
    elif resp['currency']=='eur':
      return {'price':str(float(resp['unit_amount']/100)) + '€'}
    elif resp['currency']=='gbp':
      return {'price':str(float(resp['unit_amount']/100)) + '£'}
  except Exception as e:
    print(e)
    return jsonify(error=str(e)), 403

@app.route('/payment_webhook',methods=['POST'])
@cross_origin()
def payment_webhook():
  data = json.loads(request.data)
  sig = request.headers['Stripe-Signature']
  event = None

  try:
    event = stripe.Webhook.construct_event(
      request.data, sig, endpoint_secret
    )
  except ValueError as e:
    # Invalid payload
    print("hata wvrdi")
    return jsonify(error=str(e)), 500
  except stripe.error.SignatureVerificationError as e:
    # Invalid signature
    print("hata verdi")
    return jsonify(error=str(e)), 500

  # Handle the checkout.session.completed event
  if event['type'] == 'checkout.session.completed':
    print("edoş wrote this")
    session = event['data']['object']
    user_id = session['metadata']['user_id']
    print(user_id)
    # Fulfill the purchase...
    handle_checkout_session(session,user_id)

    return jsonify(message='Payment was successful'), 200
  
@app.route('/create_checkout_session',methods=['POST'])
@cross_origin()
def create_checkout():
  data = json.loads(request.data)
  user_id = get_key_if_exist('user_id',data)
  if user_id:
    session = stripe.checkout.Session.create(
      payment_method_types=['card'],
      line_items=[{
        'price': os.environ.get('STRIPE_PRICE_ID'),
        'quantity': 1,
      }],
      mode='subscription',
      metadata={
        'user_id':user_id
      },
      success_url=os.environ.get('DOMAIN_NAME')+'/success?session_id={CHECKOUT_SESSION_ID}',
      cancel_url=os.environ.get('DOMAIN_NAME')+'/cancel',
    )
    return session, 200
  else:
    return jsonify(error='No user_id supplied with request'), 500
@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe_Signature', None)

    if not sig_header:
        return 'No Signature Header!', 400

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        # Invalid payload
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return 'Invalid signature', 400

    if event['type'] == 'payment_intent.succeeded':
        email = event['data']['object']['receipt_email'] # contains the email that will recive the recipt for the payment (users email usually)
        
        user_info['paid_50'] = True
        user_info['email'] = email
    if event['type'] == 'invoice.payment_succeeded':
        email = event['data']['object']['customer_email'] # contains the email that will recive the recipt for the payment (users email usually)
        customer_id = event['data']['object']['customer'] # contains the customer id
        
        user_info['paid'] = True
    else:
        return 'Unexpected event type', 400

    return '', 200

@app.route('/user', methods=['GET'])
def user():
    return user_info, 200
    
if __name__ == "__main__":
  app.run(debug=True)
