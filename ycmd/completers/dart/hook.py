#!/usr/bin/env python
#
# Copyright (C) 2015  Google Inc.
#
# This file is part of YouCompleteMe.
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

import logging
from ycmd.completers.dart.dart_completer import \
    DartCompleter, FindDartAnalysisServer

_logger = logging.getLogger(__name__)

def GetCompleter( user_options ):
  binary = FindDartAnalysisServer(user_options)
  if binary:
    _logger.info("Enabling Dart completion using %s", binary)
    return DartCompleter(user_options)
  _logger.info("Could not find analysis_server binary, no Dart completion.")
  return None

