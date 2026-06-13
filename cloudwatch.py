import os
import time
import boto3
from botocore.exceptions import ClientError

# Read configuration
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
ENABLE_CLOUDWATCH = os.getenv('ENABLE_CLOUDWATCH', 'false').lower() == 'true'

# Determine if CloudWatch client is active
USE_CLOUDWATCH = all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, ENABLE_CLOUDWATCH])

cw_logs_client = None
cw_metrics_client = None
sequence_token = None

if USE_CLOUDWATCH:
    try:
        cw_logs_client = boto3.client(
            'logs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        cw_metrics_client = boto3.client(
            'cloudwatch',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        print("Connected to AWS CloudWatch Logs and Metrics successfully.")
    except Exception as e:
        print(f"Failed to connect to CloudWatch: {e}. Graceful local logging fallback active.")
        USE_CLOUDWATCH = False

def log_event(message, log_group="CertifyPro/ApplicationLogs", log_stream="AppServerStream"):
    """
    Pushes application logs directly to AWS CloudWatch Logs.
    """
    global sequence_token
    
    timestamp = int(round(time.time() * 1000))
    print(f"[LOCAL LOG] [{log_stream}] {message}")
    
    if not USE_CLOUDWATCH or not cw_logs_client:
        return False
        
    try:
        # Try to put log events. If group/stream doesn't exist, handle the exception and create them.
        try:
            kwargs = {
                'logGroupName': log_group,
                'logStreamName': log_stream,
                'logEvents': [
                    {
                        'timestamp': timestamp,
                        'message': message
                    }
                ]
            }
            if sequence_token:
                kwargs['sequenceToken'] = sequence_token
                
            response = cw_logs_client.put_log_events(**kwargs)
            sequence_token = response.get('nextSequenceToken')
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'ResourceNotFoundException':
                # Create group and stream
                try:
                    cw_logs_client.create_log_group(logGroupName=log_group)
                except ClientError as ex:
                    if ex.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                        raise ex
                        
                try:
                    cw_logs_client.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
                except ClientError as ex:
                    if ex.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                        raise ex
                
                # Retry log placement
                response = cw_logs_client.put_log_events(
                    logGroupName=log_group,
                    logStreamName=log_stream,
                    logEvents=[{'timestamp': timestamp, 'message': message}]
                )
                sequence_token = response.get('nextSequenceToken')
                return True
                
            elif error_code == 'InvalidSequenceTokenException':
                sequence_token = e.response['Error']['Message'].split('is: ')[-1]
                # Retry with updated token
                response = cw_logs_client.put_log_events(
                    logGroupName=log_group,
                    logStreamName=log_stream,
                    logEvents=[{'timestamp': timestamp, 'message': message}],
                    sequenceToken=sequence_token
                )
                sequence_token = response.get('nextSequenceToken')
                return True
            else:
                print(f"CloudWatch Log ClientError: {e}")
                return False
    except Exception as e:
        print(f"Failed to log event to CloudWatch: {e}")
        return False

def push_metric(metric_name, value, unit='Percent', namespace='CertifyPro/Metrics'):
    """
    Publishes custom telemetry indicators to AWS CloudWatch Metrics.
    """
    if not USE_CLOUDWATCH or not cw_metrics_client:
        # Silently skip if disabled
        return False
        
    try:
        cw_metrics_client.put_metric_data(
            Namespace=namespace,
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': float(value),
                    'Unit': unit,
                    'Timestamp': time.time()
                }
            ]
        )
        return True
    except Exception as e:
        print(f"Failed to publish metric to CloudWatch: {e}")
        return False
