import json
import boto3
import logging
import ask_sdk_core.utils as ask_utils
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION   = "us-east-1"
REPROMPT = "What else would you like to know about the fan?"


dynamodb = boto3.resource("dynamodb", region_name=REGION)
TABLE    = dynamodb.Table("user_thing")   # tabla: user_id (PK) → thing_name

def get_thing_name(handler_input):
    user_id = handler_input.request_envelope.session.user.user_id

    response = TABLE.get_item(
        Key={"user_id": user_id}
    )

    item = response.get("Item")

    if item:
        return item["thing_name"]

    TABLE.put_item(
        Item={
            "user_id": user_id,
            "thing_name": "Esp32Ventilador"
        }
    )

    return "Esp32Ventilador"




def get_iot_data_client():
    iot = boto3.client("iot", region_name=REGION)
    endpoint = iot.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
    return boto3.client(
        "iot-data",
        region_name=REGION,
        endpoint_url=f"https://{endpoint}",
    )




def get_shadow_state(thing_name: str) -> dict:
   
    client = get_iot_data_client()
    response = client.get_thing_shadow(thingName=thing_name)
    return json.loads(response["payload"].read())

def get_shadow_variable(thing_name: str, variable: str,
                        section: str = "reported", default=None):
    
    try:
        payload = get_shadow_state(thing_name)
        return payload.get("state", {}).get(section, {}).get(variable, default)
    except Exception as e:
        logger.error(f"Error obtaining {variable} from {section}: {e}")
        return default




def update_shadow_desired(thing_name: str, desired: dict) -> bool:
   
    try:
        client = get_iot_data_client()
        client.update_thing_shadow(
            thingName=thing_name,
            payload=json.dumps({"state": {"desired": desired}})
        )
        return True
    except Exception as e:
        logger.error(f"Error updating desired shadow {desired}: {e}")
        return False



def speak(handler_input, text: str, keep_session: bool = True):
    
    rb = handler_input.response_builder.speak(text)
    if keep_session:
        rb = rb.ask(REPROMPT)
    return rb.response




class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        text = (
            "Welcome to the fan control. "
            "You can ask me about the temperature, humidity, speed, "
            "complete status, turn on or off the automatic mode, "
            "change the temperature threshold, or change the speed."
        )
        return speak(handler_input, text)




class HelloIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("HelloIntent")(handler_input)

    def handle(self, handler_input):
        return speak(handler_input,
                     "Hello! I'm here to help you control your fan.")



class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        text = (
            "You can ask me: temperature, humidity, current speed, complete status, "
            "turn on the fan, turn off the fan, "
            "enable or disable the automatic mode, "
            "change the threshold to a number, "
            "or change the speed to a number between zero and one hundred."
        )
        return speak(handler_input, text)



class GetTemperatureIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetTemperatureIntent")(handler_input)

    def handle(self, handler_input):
        try:
            thing = get_thing_name(handler_input)
            temp  = get_shadow_variable(thing, "temperature")
            text  = (f"The current temperature is {temp} degrees Celsius."
                     if temp is not None
                     else "I couldn't retrieve the temperature, the sensor is not available.")
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)




class GetHumidityIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetHumidityIntent")(handler_input)

    def handle(self, handler_input):
        try:
            thing    = get_thing_name(handler_input)
            humidity = get_shadow_variable(thing, "humidity")
            text     = (f"The current humidity is {humidity} percent."
                        if humidity is not None
                        else "I couldn't retrieve the humidity, the sensor is not available.")
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)




class GetSpeedLevelIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetSpeedLevelIntent")(handler_input)

    def handle(self, handler_input):
        try:
            thing = get_thing_name(handler_input)
            speed = get_shadow_variable(thing, "speed")
            if speed is None:
                text = "I couldn't retrieve the fan speed."
            elif speed == 0:
                text = "The fan is off, its speed is zero."
            else:
                text = f"The current speed of the fan is {speed}."
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)




class GetAllValuesIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetAllValuesIntent")(handler_input)

    def handle(self, handler_input):
        try:
            thing    = get_thing_name(handler_input)
            payload  = get_shadow_state(thing)
            reported = payload.get("state", {}).get("reported", {})

            speed     = reported.get("speed")
            temp      = reported.get("temperature")
            humidity  = reported.get("humidity")
            auto_mode = reported.get("autoMode")
            threshold = reported.get("tempThreshold")

            if any(v is None for v in [speed, temp]):
                text = "I couldn't retrieve the complete status of the fan."
            else:
                estado   = "off" if speed == 0 else f"on at speed {speed}"
                auto_str = "enabled" if auto_mode else "disabled"
                hum_str  = f"{humidity} percent" if humidity is not None else "not available"
                thr_str  = f"{threshold} degrees" if threshold is not None else "not configured"

                text = (
                    f"Complete status of the fan: "
                    f"the fan is {estado}. "
                    f"Temperature {temp} degrees Celsius. "
                    f"Humidity {hum_str}. "
                    f"Automatic mode {auto_str}. "
                    f"Temperature threshold {thr_str}."
                )
        except Exception as e:
            logger.error(f"GetAllValuesIntent error: {e}")
            text = "There was an error retrieving the complete status."
        return speak(handler_input, text)




class UpdateSpeedLevelIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("UpdateSpeedLevelIntent")(handler_input)

    def handle(self, handler_input):
        slots     = handler_input.request_envelope.request.intent.slots
        raw_speed = slots.get("speed") and slots["speed"].value

        if raw_speed is None:
            return speak(handler_input,
                         "What speed would you like to set the fan to? "
                         "Say a number between zero and one hundred.")
        try:
            speed = int(float(raw_speed))
        except (ValueError, TypeError):
            return speak(handler_input,
                         "I didn't understand the number. Say a speed between zero and one hundred.")

        if not (0 <= speed <= 100):
            return speak(handler_input,
                         f"{speed} is out of range. "
                         "The speed must be between zero and one hundred.")
        try:
            thing = get_thing_name(handler_input)
            ok    = update_shadow_desired(thing, {"speed": speed})
            if ok:
                text = ("The fan has been turned off."
                        if speed == 0
                        else f"Speed updated to {speed}.")
            else:
                text = "I couldn't update the speed. Please try again."
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)




class SetAutoModeIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SetAutoModeIntent")(handler_input)

    def handle(self, handler_input):
        intent = handler_input.request_envelope.request.intent
        slots = intent.slots if intent.slots else {}

        action = (
            slots.get("autoAction").value
            if slots.get("autoAction")
            else None
        )

        if action is None:
            return speak(handler_input,
                         "What would you like to do? Say 'activate' or 'deactivate' automatic mode.")

        action_lower = action.lower()
        if any(w in action_lower for w in ["activ", "encend", "on"]):
            auto_mode = True
            confirm   = "Automatic mode activated. The fan will turn on automatically when the temperature threshold is exceeded."
        elif any(w in action_lower for w in ["desactiv", "apag", "off"]):
            auto_mode = False
            confirm   = "Automatic mode deactivated."
        else:
            return speak(handler_input,
                         "I didn't understand. Say 'activate' or 'deactivate' automatic mode.")
        try:
            thing = get_thing_name(handler_input)
            ok    = update_shadow_desired(thing, {"autoMode": auto_mode})
            text  = confirm if ok else "I couldn't change the automatic mode. Please try again."
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)



class GetAutoModeIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetAutoModeIntent")(handler_input)

    def handle(self, handler_input):
        try:
            thing     = get_thing_name(handler_input)
            auto_mode = get_shadow_variable(thing, "autoMode")
            threshold = get_shadow_variable(thing, "tempThreshold")

            if auto_mode is None:
                text = "I couldn't retrieve the status of the automatic mode."
            else:
                estado = "enabled" if auto_mode else "disabled"
                thr_str = (f" The configured threshold is {threshold} degrees."
                           if threshold is not None else "")
                text = f"The automatic mode is {estado}.{thr_str}"
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)




class SetTempThresholdIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SetTempThresholdIntent")(handler_input)

    def handle(self, handler_input):
        slots       = handler_input.request_envelope.request.intent.slots
        raw_thresh  = slots.get("threshold") and slots["threshold"].value

        if raw_thresh is None:
            return speak(handler_input,
                         "What temperature would you like the fan to activate automatically? "
                         "Say a number in degrees Celsius.")
        try:
            threshold = int(float(raw_thresh))
        except (ValueError, TypeError):
            return speak(handler_input,
                         "I didn't understand the number. Say the temperature in degrees Celsius.")

        if not (0 <= threshold <= 60):
            return speak(handler_input,
                         f"{threshold} degrees is out of range. "
                         "The threshold must be between 0 and 60 degrees.")
        try:
            thing = get_thing_name(handler_input)
            ok    = update_shadow_desired(thing, {"tempThreshold": threshold})
            text  = (f"Temperature threshold updated to {threshold} degrees. "
                     f"The fan will activate automatically if the temperature exceeds this value."
                     if ok
                     else "I couldn't update the threshold. Please try again.")
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)




class GetTempThresholdIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetTempThresholdIntent")(handler_input)

    def handle(self, handler_input):
        try:
            thing     = get_thing_name(handler_input)
            threshold = get_shadow_variable(thing, "tempThreshold")
            text      = (f"The temperature threshold is set to {threshold} degrees Celsius."
                         if threshold is not None
                         else "No threshold is configured.")
        except Exception as e:
            logger.error(e)
            text = "I couldn't identify your fan. Please check your account."
        return speak(handler_input, text)




class CancelAndStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (
            ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input)
            or ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input)
        )

    def handle(self, handler_input):
       
        return handler_input.response_builder.speak("Goodbye.").response




class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error(f"Exception not handled: {exception}", exc_info=True)
        return speak(handler_input,
                     "There was an issue. Please try again.")




sb = SkillBuilder()

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(HelloIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(GetTemperatureIntentHandler())
sb.add_request_handler(GetHumidityIntentHandler())
sb.add_request_handler(GetSpeedLevelIntentHandler())
sb.add_request_handler(GetAllValuesIntentHandler())
sb.add_request_handler(UpdateSpeedLevelIntentHandler())
sb.add_request_handler(SetAutoModeIntentHandler())
sb.add_request_handler(GetAutoModeIntentHandler())
sb.add_request_handler(SetTempThresholdIntentHandler())
sb.add_request_handler(GetTempThresholdIntentHandler())
sb.add_request_handler(CancelAndStopIntentHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()