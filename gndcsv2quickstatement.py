import csv
import codecs
import re
import sys
import urllib

pre = re.compile(r"(p|qal|s)(?P<pid>\d+)",  re.IGNORECASE)

VALID_TYPES = [
    'text/csv',
    'text/plain',
    'text/x-csv',
    'application/csv',
    'text/comma-separated-values',
    'application/excel',
    'application/vnd.ms-excel',
    'application/vnd.msexcel',
    'text/anytext',
    'application/octet-stream',
    'application/txt']


def get_prop_types(props):
    # Query : http://tinyurl.com/yc4q5upl
    with open('property-types.csv') as property_types:
        reader = csv.DictReader(property_types)
        properties = {}
        for row in reader:
            p = row['property']
            if p in props:
                properties[p] = row['type']
        return properties

def strip_comments(str):
    exploded = str.split('|')
    return exploded[0].strip()

def format_value(value, proptype, key, warnings):
    # Pepare the format warning just in case
    format_warning = "{} expects a {} but {} does not match the format".format(
        key,
        proptype,
        value)

    # If it looks like an Item/Property/Lexeme, just treat it that way
    # proptypes: WikibaseItem, WikibaseProperty, WikibaseLexeme, WikibaseSense, WikibaseForm
    v = re.match("^(https?\:\/\/www\.wikidata\.org\/entity\/)?(?P<qid>(L|P|Q)\d+(-(S|F)\d+)?)", value)
    if v is not None:
        value = v.group('qid')
    # Manage unknown or novalue statements
    elif value in ['somevalue', 'novalue']:
        pass
    elif proptype in ["String", "ExternalId", "CommonsMedia", "TabularData", "Url", "Math"]:
            if not re.match("^\".*\"$", value):
                value = "\"{}\"".format(value)
        # Todo: add warnings for URLs that include characters not managed by QS
    elif proptype == 'Monolingualtext':
        if not re.match("^[a-zA-Z0-9-]+\:\".*\"$", value):
            warnings.append(format_warning)
            value = ""
    elif proptype == 'Quantity':
        if not re.match("^-?[\d.]+(~-?[\d.]+|\[-?[\d.]+,-?[\d.]+\])?(U\d+)?$", value):
            warnings.append(format_warning)
            value = ""
    elif proptype == 'Time':
        if re.match("^[+-]\d{4,}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\/\d{1,2}$", value):
            pass
        elif re.match("^(?P<sign>[+-])?(?P<year>\d{1,})(-(?P<month>\d{2}))?(-(?P<day>\d{2}))?$", value):
            v = re.match("^(?P<sign>[+-])?(?P<year>\d{1,})(-(?P<month>\d{2}))?(-(?P<day>\d{2}))?$", value)
            if v.group('sign'):
                sign = v.group('sign')
            else:
                sign = '+'

            if v.group('day'):
                day = v.group('day')
                precision = '11' #day
            else:
                day = '00'

            if v.group('month'):
                month = v.group('month')
                if not v.group('day'):
                    precision = '10' # month
            else:
                month = '00'
                precision = '9' # year

            year =  '{:04}'.format(int(v.group('year')))

            value = '{}{}-{}-{}T00:00:00Z/{}'.format(
                sign,
                year,
                month,
                day,
                precision)

        else:
            warnings.append(format_warning)
            value = ""
    elif proptype == 'GlobeCoordinate':
        if not re.match("^@[\d.]+/[\d.]+$", value):
            warnings.append(format_warning)
            value = ""

    # Todo: GlobeCoordinate
    return value

def handle_file(csvfile):
    #reader = csv.DictReader(codecs.iterdecode(csvfile, 'utf-8'))
    reader = csv.DictReader(open(csvfile))

    fieldnames = list(reader.fieldnames)
    props = ['P' + pre.match(x).group('pid') for x in fieldnames if pre.match(x) is not None]
    proptype = get_prop_types(props)

    all_commands = ""
    import_url = ""
    warnings = []
    for row in reader:
        commands_array = []
        sources = []

        for key in fieldnames:
            value = row[key]
            key = strip_comments(key).lower()

            if key == '':
                warnings.append('Unidentified property for value {}.'.format(value))
            elif key == 'qid': # The Qid
                if value == '':
                    commands_array.append('CREATE')
                    qid = 'LAST'
                else:
                    qid = format_value(value, 'WikibaseItem', key, warnings)
            elif re.match("^s[0-9]+", key): # The source
                if value:
                    pid = 'P' + key[1:]
                    value = format_value(value, proptype[pid], key, warnings)
                    if value:
                        sources.append('{}\t{}'.format(key.upper(), value))
            elif re.match("^p[0-9]+", key): # Main properties
                if value:
                    pid = key.upper()
                    value = format_value(value, proptype[pid], key, warnings)
                    if value:
                        commands_array.append('{}\t{}\t{}\t{}'.format(
                            qid,
                            pid,
                            value,
                            '\t'.join(sources)))
            elif re.match("^qal[0-9]+", key): # Qualifiers
                if value:
                    pid = 'P' + key[3:]
                    value = format_value(value, proptype[pid], key, warnings)
                    if value:
                        if len(commands_array):
                            last = commands_array.pop()
                            commands_array.append('{}\t{}\t{}'.format(
                                last,
                                pid.upper(),
                                value))
                        else:
                            warnings.append("You seem to try to apply a {} qualifier without a property before".format(key))
            elif re.match("^(l|d|s)(?P<lang>[a-z-]+)$", key): # Labels, Descriptions and Sitelinks
                if value:
                    value = format_value(value, "String", key, warnings)
                    if value:
                        commands_array.append('{}\t{}\t{}'.format(
                            qid,
                            key.title(),
                            value))
            elif re.match("^a(?P<lang>[a-z-]+)$", key): # Aliases
                values = value.split('|')
                for v in values:
                    if v:
                        v = format_value(v, "String", key, warnings)
                        commands_array.append('{}\t{}\t{}'.format(
                            qid,
                            key.title(),
                            v))
            else:
                warnings.append("Unidentified property: {}".format(key))

        if len(commands_array):
            all_commands += '\n'.join(commands_array) + '\n'


    if len(all_commands):
        all_commands = all_commands.strip()

    results = {
        'all_commands': all_commands,
        'warnings': warnings }
    return results

if len(sys.argv) != 2:
	print('Usage python gndcsv2quickstatement.py input.csv')
	exit(1)

filename = sys.argv[1];
print(results['all_commands'])
