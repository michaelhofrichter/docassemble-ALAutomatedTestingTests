from github import Github
import requests
import re
from nacl import encoding, public
import codecs
from base64 import b64encode
import json
from docassemble.base.util import log, zip_file, defined
from docassemble.base.core import DAObject
from docassemble.base.util import DAFile, DAFileCollection

# reference:
# Mostly: https://pygithub.readthedocs.io/en/latest/introduction.html
# commit: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_git_commit
# branch? https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_git_ref
# pull: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_pull
# repo key: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.get_keys

# https://gist.github.com/JeffPaine/3145490
# https://docs.github.com/en/free-pro-team@latest/rest/reference/issues#create-an-issue
# https://github.com/SuffolkLITLab/docassemble-GithubFeedbackForm
# https://vaibhavsagar.com/blog/2020/05/04/github-secrets-api/
# https://github.com/berit/docassemble-initializecucumber/blob/main/docassemble/initializecucumber/test.py
# Create org secret: https://docs.github.com/en/rest/reference/actions#create-or-update-an-organization-secret
# Create repo secret: https://docs.github.com/en/rest/reference/actions#create-or-update-a-repository-secret


class TestInstaller(DAObject):
  def init( self, *pargs, **kwargs ):
    super().init(*pargs, **kwargs)
  
  def send_da_auth_secrets( self ):
    """Set GitHub repo secrets the tests need to log into the da server and
    create projects to run interviews to test."""
    # PyGithub cannot currently handle secrets
    self.set_github_auth()
    self.put_secret( secret_name='PLAYGROUND_EMAIL', secret_value=self.email )
    self.put_secret( secret_name='PLAYGROUND_PASSWORD', secret_value=self.password )
    self.set_da_server_info()
    self.put_secret( secret_name='PLAYGROUND_ID', secret_value=self.playground_id )
    return self
  
  def put_secret( self, secret_name='', secret_value='' ):
    """Add one secret to the GitHub repo."""
    # Convert the message and key to Uint8Array's (Buffer implements that interface)
    encrypted_key = public.PublicKey( self.public_key.encode("utf-8"), encoding.Base64Encoder() )
    sealed_box = public.SealedBox( encrypted_key )
    # Encrypt using LibSodium.
    encrypted = sealed_box.encrypt( secret_value.encode( "utf-8" ))
    # Base64 the encrypted secret
    base64_encrypted = b64encode( encrypted ).decode( "utf-8" )
    #log( 'base64_encrypted', 'console' )
    #log( base64_encrypted, 'console' )
    
    secret_url = self.github_repo_base + "/actions/secrets/" + secret_name
    secret_payload = '{"encrypted_value":"' + base64_encrypted + '", "key_id":"' + self.key_id + '"}'
    secret_headers = {
      'Accept': "application/vnd.github.v3+json",
      'Authorization': self.basic_auth,
    }
    
    secret_response = requests.request( "PUT", secret_url, data=secret_payload, headers=secret_headers )
    #log( 'secret_response.text', 'console' )
    #log( secret_response.text, 'console' )
    
    # TODO: Check there was no error
    
    # Cannot get the value of the secret to see if we're setting it correctly
    # Can at least check that the secret exists
    response = requests.request( "GET", secret_url, data="", headers=secret_headers )
    #log( response.text, 'console' )
    
    return self

  def set_github_auth( self ):
    """Set values needed for GitHub authorization.
    Needs self.user_name, self.repo_name, and self.token."""
    self.get_github_info_from_repo_url() # gets self.user_name, self.repo_name
    
    # May not need user name with this library
    self.github = Github(self.token)
    self.user_name = self.github.get_user().name
    
    # The value for the GitHub 'Authorization' key
    auth_bytes = codecs.encode(bytes( self.user_name + ':' + self.token, 'utf8'), 'base64')
    self.basic_auth = 'Basic ' + auth_bytes.decode().strip()
    
    # The base url string needed for making requests to the repo.
    # TODO: Might need this only for secrets now with new lib
    self.github_repo_base = "https://api.github.com/repos/" + self.user_name + "/" + self.repo_name
    
    self.set_key_values()
    return self
  
  def get_github_info_from_repo_url( self ):
    """Use repo address to parse out user name and repo name. Needs self.repo_url"""
    matches = re.match(r"https:\/\/github.com\/([^\/]*)\/([^\/]*)", self.repo_url)
    if matches:
      self.repo_name = matches.groups(1)[1]
    else:
      self.repo_name = None
    #log( 'self.repo_name', 'console' )
    #log( self.repo_name, 'console' )
    return self
  
  def set_key_values( self ):
    """Gets and sets GitHub key id for the repo. Needed for auth to
    set secrets, etc. Needs set_github_auth()"""
    key_url = self.github_repo_base + "/actions/secrets/public-key"
    key_payload = ""
    key_headers = {
      'Accept': 'application/vnd.github.v3+json',
      'Authorization': self.basic_auth,
    }
    
    key_response = requests.request( 'GET', key_url, data=key_payload, headers=key_headers )
    key_json = json.loads( key_response.text )
    self.key_id = key_json[ 'key_id' ]
    self.public_key = key_json[ 'key' ]
    return self
    
  def set_da_server_info( self ):
    """Use the interview url to get the user's Playground id."""
    # Can probably do both in one match, but maybe we want to get granular with
    # our error messages...?
    server_match = re.match( r"^(.+)\/interview\?i=docassemble\.playground", self.playground_url)
    if server_match is None:
      self.server_url = None
    else:
      self.server_url = server_match.group(1)
      
    id_match = re.match( r"^.+(?:interview\?i=docassemble\.playground)(\d+)(?:.*)$", self.playground_url )
    if id_match is None:
      self.playground_id = None
    else:
      self.playground_id = id_match.group(1)
    
    return self
  
  def set_repo( self ):
    self.repo = self.github.get_user().get_repo( self.repo_name )
  
  def create_branch( self ):
    # Get default branch
    if not defined( 'installer.repo' ):
      self.set_repo()
    repo = self.repo
    default_branch_name = repo.default_branch
    default_branch = repo.get_branch( default_branch_name )
    
    self.errors = []
    branch_name_base = "automated_testing"
    branch_name = branch_name_base
    ref_path = "refs/heads/" + branch_name  # path of new branch
    count = 1
    max_count = 20
    while ( count < max_count ):
      # except github.GithubException.GithubException as error:
      try:
        response = repo.create_git_ref( ref_path, default_branch.commit.sha )
        break
      except Exception as error:
        count += 1
        branch_name = branch_name_base + '_' + str( count )
        ref_path = "refs/heads/" + branch_name
        # Why does this make things get stuck on a previous page? (first page?)
        # Some kind of exception in here? Lets hope it doesn't occur at all.
        if count == max_count:
          # TODO: Tell the user to delete old branches
          self.errors.append( error )
          
    if len(self.errors) > 0 and not self.errors[0].status == 422:
      log( 'non-422 error', 'console' )
      log( self.errors, 'console' )
    
    #self.ref_path = ref_path
    self.branch_name = branch_name
    return self
  
  def commit_files( self ):
    # https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_file
    # https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_git_commit
    # https://docs.github.com/en/rest/reference/repos#create-or-update-file-contents
    # https://docs.github.com/en/rest/reference/repos#contents
    # https://stackoverflow.com/questions/20045572/create-folder-using-github-api
    # https://stackoverflow.com/questions/22312545/github-api-to-create-a-file
    
    # Create a commit?
    # https://docs.github.com/en/rest/reference/git#list-matching-references
    
    # Check mergability of a PR
    # https://docs.github.com/en/rest/guides/getting-started-with-the-git-database-api#checking-mergeability-of-pull-requests
    
    # > I'd just slurp the file contents into a string with open() and .read() and then use re.sub
    
    #log( self.run_interview_tests, 'console' )
    #contents = self.run_interview_tests.slurp()
    #log( 'slurp', 'console' )
    #log( contents, 'console' )
    
    # Get the folder with the files
    #files_repo = 
    # https://raw.githubusercontent.com/plocket/docassemble-cucumber/main/pushing_testing_files/.env-example
    
    #if not defined( 'installer.repo' ):
    #  self.set_repo()
    #repo = self.repo
    
    # TODO: This will overwrite file in existing branch if page is refreshed instead of interview being redone. Does it need fixing?
    self.repo.create_file('.github/workflow/file.yml', 'add file', self.run_interview_tests_str, branch=self.branch_name)
    
    #self.initializeAttribute('gitignore', DAFile)
    #self.gitignore.initialize( filename='.gitignore', attachment=True )
    #self.gitignore.write( self.gitignore_str )
    #self.gitignore.commit()
    
    self.repo.create_file('.gitignore', 'add file', self.gitignore_str, branch=self.branch_name)
    
    return self
  
  def add_file_to_branch( self ):
    return self
#
#  def get_files( self ):
#    # We have the files in the templates folder
#    # though the hidden files are... invisible...
#    # and the .feature file is uneditable...
#    pass
#
#  def transform_files( self ):
#    # Don't need this as Mako does the job
#    pass
#
#  def push_to_new_branch( self ):
#    pass
#
#  def make_pull_request( self ):
#    pass
