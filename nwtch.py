import os
import urllib2
import string
import re
import datetime
from google.appengine.api import users
from google.appengine.api import urlfetch
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.api import mail
from google.appengine.ext.webapp.util import run_wsgi_app
from HTMLParser import HTMLParser


## Objects

class Flight(db.Model):

  date = db.StringProperty()
  price = db.ListProperty(int)

  def __repr__(self):
    if self.price[0] and self.price[1]:
      return "{Date: %s, Price: %i.%i}" % (self.date, self.price[0], self.price[1])
    else:
      return "{Date: %s, Price: No flight}" % (self.date)
  def __eq__(self, other):
    return self.date == other.date and self.price == other.price

## DB

class UserPref(db.Model):

  user = db.UserProperty()
  last = db.ListProperty(db.Key)
  now = db.ListProperty(db.Key)
  dt = db.DateTimeProperty(auto_now=True)
  tz = db.IntegerProperty()
  
  fd = db.DateProperty()
  
  def date(self):
    return (self.dt + datetime.timedelta(hours = self.tz)).ctime()
    
  @staticmethod
  def getdata(u):
    q = db.GqlQuery("SELECT * FROM UserPref WHERE user = :1", u)
    return q.get()

## App

class infoParser(HTMLParser):
  def __init__(self):
    self.result = []
    self.save_price = False
    self.save_date = False
    self.day_check = False
    self.day = 0
    HTMLParser.__init__(self)

  def handle_data(self, data):
    if self.save_price: 
      self.flight.price.append(int(re.sub("\xc2\xa3","",data)))
    elif self.save_date:
      self.flight.date = re.sub("\n","",data)
    
  def handle_starttag(self, tag, attrs):
    if tag == "div" and len(attrs) > 0 and attrs[0][1] == "day": 
      self.day = self.day + 1
      self.day_check = True
    elif tag == "span" and len(attrs) == 0 and self.day_check and not self.save_price and self.day in range(2,5):
      self.flight = Flight()
      self.flight.put()
      self.result.append(self.flight.key())
      self.save_date = True
    elif tag == "span" and len(attrs) > 0 and attrs[0][1] == "priceSmaller" and self.day_check:
      self.save_price = True

  def handle_endtag(self, tag):
    # print "Encountered the end of a %s tag" % tag
    if tag == "div" and self.day_check and self.day in range(2,5):
      self.flight.put()
      self.day_check = False
    elif tag == "span":
      self.save_price = False
      self.save_date = False

def cookieStrip(cookieString):
  mycookies = ""
  L = string.split(cookieString, ",")
  for cookie in L:
    LL = string.split(cookie, ";")
    if re.search('.*?=.*?',LL[0]):
      mycookies = "%s %s;" % (mycookies, LL[0])
  return mycookies
    
    
def getPrice(up): 

    ## Acquiring cookies

    url = "http://www.easyjet.com/asp/en/book/index.asp"

    result = urlfetch.fetch(url)
    cookies = cookieStrip(result.headers['set-cookie'])


    ## Search for flights

    host = "http://www.easyjet.com"
    request = "/en/Booking.mvc/SearchForFlights?origAirportCode=*LO&destAirportCode=BIO&departureDay=%s&departureMonthYear=122010&returnDay=00&returnMonthYear=00&numberOfAdults=1&numberOfChildren=0&numberOfInfants=0&flexibleOnDates=false&email=" % (up.fd.day)

    url = "%s%s" % (host, request)

    result = urlfetch.fetch(url, headers = { 'cookie': cookies }, follow_redirects = False)

    cookies = "%s %s ej20SearchCookie=ej20Search_0=*LO|BIO|%s/12/2010||1|0|0|False||0;" % (cookies, cookieStrip(result.headers['set-cookie']), up.fd.day)


    ## Making request

    request = "/en/Booking.mvc"

    url = "%s%s" % (host, request)

    result = urlfetch.fetch(url, headers = { 'cookie': cookies })

    stream = result.content
    stream = re.sub("onclick=.*? ", "", stream)
    stream = re.sub("<script>.*?</script>", "", stream)

    parser = infoParser()
    parser.feed(stream)
    parser.close()

    return parser.result
    
def eq_prix(web, user):
  ins_web = Flight.get(web)
  ins_user = Flight.get(user)
  if len(ins_web) > 0:
    return ins_web == ins_user
  else:
    return True
  
#### Returns False if the prices have NOT changed ###
def check(up):
  price_now = getPrice(up)
  if not eq_prix(price_now, up.now):
    if up.last != up.now: 
      for fl in Flight.get(up.last): 
        if fl: fl.delete()
    up.last = up.now
    up.now = price_now
    up.put()
    return True
  else:
    for fl in Flight.get(price_now): fl.delete()
    return False

## Web Apps

  ## Pref ##  
class Pref(webapp.RequestHandler):
  def get(self):
    user = users.get_current_user()
    tz = self.request.get('tz')
    day = self.request.get('day')
    
    up = UserPref.getdata(user)
    
    if up:
      if tz == "" or day == "":
        self.response.out.write("""
          <html>
            <body>
              <h2>Pref</h2>
              <form action="/user/pref" method="get">
                <div>Time zone&nbsp;<input type="text" name="tz" size="10" value="%s"></input></div>
                <div>Day&nbsp;<input type="text" name="day" size="3" value="%s"></input></div>
                <div><input type="submit" value="Change"></div>
              </form>
            </body>
          </html>""" % (up.tz, up.fd.day))
      else:
        up.tz = int(tz)
        up.fd = datetime.date(2001,05, int(day))
        
        for fl in Flight.get(up.now): 
          if fl: fl.delete()
        for fl in Flight.get(up.last): 
          if fl: fl.delete()
          
        up.now = up.last = getPrice(up)
        up.put()
        self.redirect("/")
    else:
      self.redirect("/register")

  ## Register ##
class Register(webapp.RequestHandler):
  def get(self):
    user = users.get_current_user()
    tz = self.request.get('tz')
    day = self.request.get('day')
    
    if tz == "" or day == "":
      self.response.out.write("""
        <html>
          <body>
            <h2>Register</h2>
            <form action="/register" method="get">
              <div>Time zone&nbsp;<input type="text" name="tz" size="10"></input></div>
              <div>Day&nbsp;<input type="text" name="day" size="3"></input></div>
              <div><input type="submit" value="Register"></div>
            </form>
          </body>
        </html>""")
    else:
      if not UserPref.getdata(user):
        up = UserPref()
        up.user = user
        up.tz = int(tz)
        up.fd = datetime.date(2001,05, int(day))
        up.now = up.last = getPrice(up)
        up.put()
        self.redirect("/")
      else:
        self.redirect("/")
      
      
  ## Admin ##
class Admin(webapp.RequestHandler):
  def get(self):
  
    self.response.out.write("<h2>Users</h2><ul>")
    ups = UserPref.all()
    for up in ups:
      self.response.out.write("<li>%s (%s)</li>" % (up.user.nickname(), up.user.email()))
    self.response.out.write("</ul>")
      
  ## Check ##
class Check(webapp.RequestHandler):
  def get(self):

    user = users.get_current_user()

    userdata = UserPref.getdata(user)
    if userdata:
      if check(userdata):
        self.redirect("/?changed=1")
      else:
        self.redirect("/")
    else:
      self.redirect("register")
      
  ## Autocheck ##        
class Autocheck(webapp.RequestHandler):
  def get(self):
    user = users.get_current_user()
    ups = UserPref.all()
    for up in ups:
      if check(up): 
        mail.send_mail(sender="nightWatch <kendersec@gmail.com>",
          to="%s <%s>" % (up.user.nickname(), up.user.email()),
          subject="Your flight has changed",
          body="""The price of your flight is now: %s
            Before it was: %s""" % (Flight.get(up.now), Flight.get(up.last)))

  ## Main ##
class MainPage(webapp.RequestHandler):
  def get(self):

    user = users.get_current_user()

    
    userdata = UserPref.getdata(user)
    
    if userdata:
      self.response.out.write("<h3>Welcome %s</h3>(%s)<br/>" % (user.nickname(), user.email()))
      
      if self.request.get('changed'):
        self.response.out.write("<h3>The prices have changed</h3>")
        
      self.response.out.write("<br/>%s<br/>%s<br/<br/><br/>%s" % (Flight.get(userdata.now), Flight.get(userdata.last), userdata.date()))
      self.response.out.write("<br/><br/><a href='/user/check'>Check now</a> - <a href='/user/pref'>Pref</a> - <a href='%s'>Logout</a>" % users.create_logout_url(self.request.uri))
      
    else:
      self.redirect("/register")


application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                      ('/user/check', Check),
                                      ('/user/pref', Pref),
                                      ('/admin', Admin),
                                      ('/register', Register),
                                      ('/autocheck', Autocheck)
                                      ],
                                     debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
  
