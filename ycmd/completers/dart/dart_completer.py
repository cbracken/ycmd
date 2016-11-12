# Copyright (C) 2015 Google Inc.
#
# This file is part of ycmd.
#
# YouCompleteMe is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# YouCompleteMe is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with YouCompleteMe.  If not, see <http://www.gnu.org/licenses/>.

import json
import os.path
import subprocess
import threading

from ycmd import utils
from ycmd import responses
from ycmd.completers.completer import Completer

DART_FILETYPES = set( [ 'dart' ] )


def PathToDartBinDir( user_options ):
  sdk_dir = user_options.get( 'dart_sdk_path' )
  if not sdk_dir:
    dart_binary = utils.PathToFirstExistingExecutable( [ 'dart' ] )
    if dart_binary:
      return os.path.dirname( dart_binary )

  if not sdk_dir:
    raise RuntimeError( 'Dart SDK not found, please specify ' +
                        'g:ycm_dart_sdk_path in your .vimrc' )
  return os.path.join( sdk_dir, 'bin' )


# TODO(cbracken) Windows support
def FindDartBinary( user_options ):
  bin_dir = PathToDartBinDir( user_options )
  return os.path.join( bin_dir, 'dart' )


def FindDartAnalysisServer( user_options ):
  bin_dir = PathToDartBinDir( user_options )
  return os.path.join( bin_dir, 'snapshots', 'analysis_server.dart.snapshot' )


class AnalysisService( object ):
  def __init__( self, user_options ):
    dart_bin = FindDartBinary( user_options )
    analysis_server_path = FindDartAnalysisServer( user_options )
    flags_string = user_options.get( 'dart_analysis_server_flags' )
    flags = [] if not flags_string else flags_string.split( ' ' )
    cmd = [ dart_bin, analysis_server_path ] + flags
    self._process = utils.SafePopen( cmd,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE )
    self._request_id = 0
    self._lock = threading.RLock()


  def Kill( self ):
    self._process.kill()


  def _GetNextRequestId( self ):
    self._request_id += 1
    return str( self._request_id )


  def _SendRequestAndWaitForResults( self, method, params, result_type ):
    with self._lock:
      response = self._SendRequest( method, params )
      result_id = response[ 'id' ]
      results = [ ]
      while True:
        line = self._process.stdout.readline()
        response = json.loads( line )
        if ( ( 'event' in response )
            and ( response[ 'event' ] == result_type )
            and ( response[ 'params' ][ 'id' ] == result_id ) ):
          params = response[ 'params' ]
          results.extend( params[ 'results' ] )
          if params[ 'isLast' ]:
            return results


  def _SendRequest( self, method, params ):
    with self._lock:
      request_id = self._GetNextRequestId()
      request = { 'id': request_id, 'method': method, 'params': params }
      self._process.stdin.write( json.dumps( request ) )
      self._process.stdin.write( '\n' )
      self._process.stdin.flush()
      while True:
        line = self._process.stdout.readline()
        response = json.loads( line )
        if ( 'id' in response ) and ( response[ 'id' ] == request_id ):
          if 'error' in response:
            raise Exception( response[ 'error' ] )
          elif 'result' in response:
            return response[ 'result' ]
          else:
            return None


  def SetAnalysisRoots( self, included, excluded, packageRoots ):
    return self._SendRequest(
        'analysis.setAnalysisRoots',
        {
          'included'    : included,
          'excluded'    : excluded,
          'packageRoots': packageRoots
        } )


  def SetPriorityFiles( self, files ):
    return self._SendRequest(
        'analysis.setPriorityFiles',
        {
          'files': files
        } )


  def UpdateFileContent( self, filename, content ):
    return self._SendRequest(
        'analysis.updateContent',
        {
          'files': {
            filename: { 'type': 'add', 'content': content }
          }
        } )


  def GetErrors( self, filename ):
    return self._SendRequest(
        'analysis.getErrors',
        {
          'file': filename
        } )


  def GetNavigation( self, filename, offset, length ):
    return self._SendRequest(
        'analysis.getNavigation',
        {
          'file'  : filename,
          'offset': offset,
          'length': length
        } )


  def GetHover( self, filename, offset ):
    return self._SendRequest(
        'analysis.getHover',
        {
          'file'  : filename,
          'offset': offset
        } )


  def GetSuggestions( self, filename, offset ):
    return self._SendRequestAndWaitForResults(
        'completion.getSuggestions',
        {
          'file'  : filename,
          'offset': offset
        },
        'completion.results' )

class RequestData( object ):
  def __init__( self, request_data ):
    self.filename = request_data[ 'filepath' ]
    self.contents = utils.ToCppStringCompatible(
        request_data[ 'file_data' ][ self.filename ][ 'contents' ] )
    self.line = request_data[ 'line_num' ]
    self.column = request_data[ 'column_num' ]
    self.offset = _ComputeOffset( self.contents, self.line, self.column )

class DartCompleter( Completer ):

  _subcommands = {
    'GoToDefinition': lambda self, data: self._GoToDefinition( data ),
    'GetType'       : lambda self, data: self._GetType( data ),
  }


  def __init__( self, user_options ):
    super( DartCompleter, self ).__init__( user_options )
    self._service = AnalysisService( user_options )
    self._roots = []
    self._priority_files = []


  def DefinedSubcommands( self ):
    return DartCompleter._subcommands.keys()


  def OnUserCommand( self, arguments, request_data ):
    if not arguments:
      raise ValueError( self.UserCommandsHelpMessage() )
    command_name = arguments[ 0 ]
    if command_name in DartCompleter._subcommands:
      command = DartCompleter._subcommands[ command_name ]
      return command( self, request_data )
    else:
      raise ValueError( self.UserCommandsHelpMessage() )


  def SupportedFiletypes( self ):
    return DART_FILETYPES


  def _EnsureFileInAnalysisServer( self, filename ):
    directory = os.path.dirname( filename )
    while ( not os.path.exists( os.path.join( directory, 'pubspec.yaml' ) )
            and directory != '' and directory != '/' ):
      directory = os.path.dirname( directory )

    if directory == '' or directory == '/':
      directory = os.path.dirname( filename )

    if directory not in self._roots:
      self._roots.append( directory )
      self._service.SetAnalysisRoots( self._roots, [], {} )

    if filename not in self._priority_files:
      self._priority_files.append( filename )
      self._service.SetPriorityFiles( self._priority_files )


  def OnBufferVisit( self, request_data ):
    self._EnsureFileInAnalysisServer( request_data[ 'filepath' ] )


  def OnFileReadyToParse( self, request_data ):
    filename = request_data[ 'filepath' ]
    self._EnsureFileInAnalysisServer( filename )
    contents = request_data[ 'file_data' ][ filename ][ 'contents' ]
    self._service.UpdateFileContent( filename, contents )
    return self._GetErrorsResponseToDiagnostics(
        contents,
        self._service.GetErrors( filename ) )


  def ComputeCandidatesInner( self, request_data ):
    r = RequestData( request_data )
    self._service.UpdateFileContent( r.filename, r.contents )
    return self._SuggestionsToCandidates(
        self._service.GetSuggestions( r.filename, r.offset ) )


  def Shutdown( self ):
    self._service.Kill()


  def _GoToDefinition( self, request_data ):
    r = RequestData( request_data )
    result = self._service.GetNavigation( r.filename, r.offset, 1 )
    if 'targets' in result and 'files' in result:
      target = result[ 'targets' ][ 0 ]
      filepath = result[ 'files' ][ target[ 'fileIndex' ] ]
      return responses.BuildGoToResponse( filepath,
          target[ 'startLine' ], target[ 'startColumn' ] )
    else:
      raise RuntimeError( 'Can\'t jump to definition' )


  def _GetType( self, request_data ):
    r = RequestData( request_data )
    result = self._service.GetHover( r.filename, r.offset )
    if result[ 'hovers' ]:
      hover = result[ 'hovers' ][ 0 ]
      if 'propagatedType' in hover:
        return { 'message': hover[ 'propagatedType' ] }
      elif 'elementDescription' in hover:
        description = self._ToAscii( hover[ 'elementDescription' ] )
        return { 'message': description }
      else:
        raise Exception( 'unknown type' )
    else:
      raise Exception( 'unknown type' )


  def _GetErrorsResponseToDiagnostics( self, contents, response ):
    result = []
    for error in response[ 'errors' ]:
      location = error[ 'location' ]
      end_line, end_col = _ComputeLineAndColumn(
          contents,
          location[ 'offset' ] + location[ 'length' ] )
      result.append( {
        'location': {
          'line_num'  : location[ 'startLine' ],
          'column_num': location[ 'startColumn' ],
          'filepath'  : location[ 'file' ]
        },
        'location_extent': {
          'start': {
            'line_num'  : location[ 'startLine' ],
            'column_num': location[ 'startColumn' ]
          },
          'end': {
            'line_num'  : end_line,
            'column_num': end_col
          }
        },
        'ranges': [],
        'text': error[ 'message' ],
        'kind': error[ 'severity' ]
      } )
    return result


  def _ToAscii( self, str ):
    result = str.replace( u'\u2192', '->' )
    return result.decode( 'utf-8' ).encode( 'ascii', 'ignore' )


  def _SuggestionsToCandidates( self, suggestions ):
    result = [ ]
    suggestions.sort( key = lambda s: -s[ 'relevance' ] )
    for suggestion in suggestions:
      entry = { 'insertion_text': suggestion[ 'completion' ] }
      if 'returnType' in suggestion:
        entry[ 'extra_menu_info' ] = suggestion[ 'returnType' ]
      result.append( entry )
    return result


def _ComputeLineAndColumn( contents, offset ):
  curline = 1
  curcol = 1
  for i, byte in enumerate( contents ):
    if i == offset:
      return ( curline, curcol )
    curcol += 1
    if byte == '\n':
      curline += 1
      curcol = 1


def _ComputeOffset( contents, line, col ):
  curline = 1
  curcol = 1
  for i, byte in enumerate( contents ):
    if ( curline == line ) and ( curcol == col ):
      return i
    curcol += 1
    if byte == '\n':
      curline += 1
      curcol = 1
  return -1
