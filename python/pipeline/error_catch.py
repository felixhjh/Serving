import sys 
import enum 
import os 
import logging 
import traceback
#from paddle_serving_server.pipeline import ResponseOp
import threading
import inspect
import traceback
import functools
import re
from .proto import pipeline_service_pb2_grpc, pipeline_service_pb2
from .util import ThreadIdGenerator

_LOGGER = logging.getLogger(__name__) 

class CustomExceptionCode(enum.Enum): 
    """
    Add new Exception
    
    0           Success
    50 ~ 99     Product error
    3000 ~ 3999 Internal service error
    4000 ~ 4999 Conf error 
    5000 ~ 5999 User input error
    6000 ~ 6999 Timeout error
    7000 ~ 7999 Type Check error
    8000 ~ 8999 Internal communication error
    9000 ~ 9999 Inference error
    10000       Other error
    """
    OK = 0
    PRODUCT_ERROR = 50

    NOT_IMPLEMENTED = 3000
    CLOSED_ERROR = 3001
    NO_SERVICE = 3002
    INIT_ERROR = 3003
    CONF_ERROR = 4000
    INPUT_PARAMS_ERROR = 5000
    TIMEOUT = 6000
    TYPE_ERROR = 7000
    RPC_PACKAGE_ERROR = 8000 
    CLIENT_ERROR = 9000
    UNKNOW = 10000


class ProductErrCode(enum.Enum):
    """
    ProductErrCode is a base class for recording business error code. 
    product developers inherit this class and extend more error codes. 
    """
    pass


class CustomException(Exception):
    def __init__(self, exceptionCode, errorMsg, isSendToUser=False):
        super().__init__(self)
        self.error_info = "\n\texception_code: {}\n"\
                          "\texception_type: {}\n"\
                          "\terror_msg: {}\n"\
                          "\tis_send_to_user: {}".format(exceptionCode.value,
                          CustomExceptionCode(exceptionCode).name, errorMsg, isSendToUser)
    
    def __str__(self):
        return self.error_info



class ErrorCatch():
    def __init__(self):
        self._id_generator = ThreadIdGenerator(
                     max_id=1000000000000000000,
                     base_counter=0,
                     step=1)

    def __call__(self, func):
        if inspect.isfunction(func) or inspect.ismethod(func):
            @functools.wraps(func)
            def wrapper(*args, **kw):
                try:
                    res = func(*args, **kw)
                except CustomException as e:
                    log_id = self._id_generator.next()
                    resp = pipeline_service_pb2.Response()
                    _LOGGER.error("\nLog_id: {}\n{}Classname: {}\nFunctionName:{}\nArgs:{}".format(log_id, traceback.format_exc(), func.__qualname__, func.__name__, args))
                    split_list = re.split("\n|\t|:", str(e))
                    resp.err_no = int(split_list[3])
                    resp.err_msg = "Log_id: {}  ErrNo: {}  Error_msg: {}  ClassName: {}  FunctionName: {}".format(log_id, resp.err_no, split_list[9], func.__qualname__ ,func.__name__ )
                    is_send_to_user = split_list[-1].replace(" ", "")
                    if is_send_to_user == "True":
                         return (None, resp)
                    else:
                        raise SystemExit("init server error occur")
                except Exception as e:
                    log_id = self._id_generator.next()
                    resp = pipeline_service_pb2.Response()
                    _LOGGER.error("\nLog_id: {}\n{}Classname: {}\nFunctionName: {}\nArgs: {}".format(log_id, traceback.format_exc(), func.__qualname__, func.__name__, args))
                    resp.err_no = CustomExceptionCode.UNKNOW.value
                    resp.err_msg = "Log_id: {}  ErrNo: {}  Error_msg: {}  ClassName: {}  FunctionName: {}".format(log_id, resp.err_no, str(e).replace("\'", ""), func.__qualname__ ,func.__name__ )
                    return (None, resp)
                    # other exception won't be sent to users.
                else:
                    resp = pipeline_service_pb2.Response()
                    resp.err_no = CustomExceptionCode.OK.value
                    resp.err_msg = ""
                    return (res, resp)

            return wrapper

def ParamChecker(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        # fetch the argument name list.
        parameters = inspect.signature(function).parameters
        argument_list = list(parameters.keys())

        # fetch the argument checker list.
        checker_list = [parameters[argument].annotation for argument in argument_list]

        # fetch the value list.
        value_list =  [inspect.getcallargs(function, *args, **kwargs)[argument] for argument in inspect.getfullargspec(function).args]

        # initialize the result dictionary, where key is argument, value is the checker result.
        result_dictionary = dict()
        for argument, value, checker in zip(argument_list, value_list, checker_list):
            result_dictionary[argument] = check(argument, value, checker, function)

        # fetch the invalid argument list.
        invalid_argument_list = [key for key in argument_list if not result_dictionary[key]]

        # if there are invalid arguments, raise the error.
        if len(invalid_argument_list) > 0:
            raise CustomException(CustomExceptionCode.INPUT_PARAMS_ERROR, "invalid arg list: {}".format(invalid_argument_list))

        # check the result.
        result = function(*args, **kwargs)
        checker = inspect.signature(function).return_annotation
        if not check('return', result, checker, function):
            raise CustomException(CustomExceptionCode.INPUT_PARAMS_ERROR, "invalid return type")

        # return the result.
        return result
    return wrapper


def check(name, value, checker, function):
    if isinstance(checker, (tuple, list, set)):
        return True in [check(name, value, sub_checker, function) for sub_checker in checker]
    elif checker is inspect._empty:
        return True
    elif checker is None:
        return value is None
    elif isinstance(checker, type):
        return isinstance(value, checker)
    elif callable(checker):
        result = checker(value)
        return result

class ParamVerify(object):
    @staticmethod
    def int_check(c, lower_bound=None, upper_bound=None):
        if not isinstance(c, int):
            return False
        if isinstance(lower_bound, int) and isinstance(upper_bound, int):
            return c >= lower_bound and c <= upper_bound
        return True

    @staticmethod
    def file_check(f):
        if not isinstance(f, str):
            return False
        if os.path.exist(f):
            return True
        else:

            return False

ErrorCatch = ErrorCatch()