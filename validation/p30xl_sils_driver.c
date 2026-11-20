/* Model-boundary replay of the production ADS controller, fusion and FSM.
 * Built as a separate DLL. Each fresh load has cold firmware static state. */
#include <math.h>
#include <string.h>
#include "main.h"
#include "base_shared.h"
#include "attdet/attitude_fusion.h"
#include "command/acs.h"
#include "control/control_defaults.h"
#include "control/control_laws.h"
#include "control/control_loop.h"
#include "control/detumbling/detumbling_MM.h"
#include "control/state_machine.h"
#include "Guidance/sun_pointing/sun_pointing_m1/sun_pointing_m1.h"
#include "Guidance/sun_pointing/sun_pointing_m2/sun_pointing_m2.h"
#include "Guidance/sun_pointing/sun_pointing_r1/sun_pointing_r1.h"
#include "Guidance/sun_pointing/sun_pointing_r2/sun_pointing_r2.h"
#include "model/sunmodel.h"
#include "utils/fdir.h"
#include "utils/utils.h"

extern void resetDefaults(void);
extern volatile uint8_t gpsFusionPositionUsable;

uint8_t sitlReplaySunTwoDofEnabled = 1;
static uint32_t tick;
static uint64_t epoch;
static uint64_t lastGpsPost;
static int trace[24];
static int transitions;

uint32_t HAL_GetTick(void) { return tick; }
unsigned p30xl_period_ms(void) { return TIME_STEP; }

void sitlReplayObserveTransition(AdsState from, AdsEvent event, AdsState to)
{
    if (transitions < (int)(sizeof(trace) / sizeof(trace[0]) / 3)) {
        trace[3 * transitions] = from;
        trace[3 * transitions + 1] = event;
        trace[3 * transitions + 2] = to;
        transitions++;
    }
}

const char *p30xl_state_name(int state)
{
    switch (state) {
    case State_Detumbling_MM: return "Detumbling_MM";
    case State_SunPointing_Master: return "SunPointing_Master";
    case State_SunPointing_R1: return "SunPointing_R1";
    case State_SunPointing_M1: return "SunPointing_M1";
    case State_SunPointing_Search: return "SunPointing_Search";
    case State_SafeMode: return "Safe";
    case State_Eclipse: return "Eclipse";
    case State_Desaturation: return "Desaturation";
    default: return "Other";
    }
}

const char *p30xl_event_name(int event)
{
    switch (event) {
    case Event_MtrDidNotWork: return "MtrDidNotWork";
    case Event_DetumblingMMTimeout: return "DetumblingMMTimeout";
    case Event_DetumbledNonEclipse: return "DetumbledNonEclipse";
    case Event_DetumbledInEclipse: return "DetumbledInEclipse";
    case Event_StartSunPointing: return "StartSunPointing";
    case Event_SunPointAchieved: return "SunPointAchieved";
    case Event_SunPointNotAchievedTimeout: return "SunPointNotAchievedTimeout";
    case Event_EnterEclipse: return "EnterEclipse";
    case Event_GpsUnavailable: return "GpsUnavailable";
    case Event_ResolvedToSunR1: return "ResolvedToSunR1";
    case Event_ResolvedToSunM1: return "ResolvedToSunM1";
    case Event_ResolvedToSunSearch: return "ResolvedToSunSearch";
    case Event_ResolvedToSafeMode: return "ResolvedToSafeMode";
    default: return "Other";
    }
}

void p30xl_init(uint64_t epoch_s, int resume_sun, int finite_difference,
               const double signs[3], int two_dof, const double attitude[4])
{
    epoch = epoch_s;
    tick = 0;
    lastGpsPost = 0;
    resetDefaults();
    compFilterInit();
    for (int i = 0; i < 4; i++)
        cmdActValues.RwTorque[i] = RW_ZERO_TORQUE;
    AdsHk.AdsTime = epoch;
    eciSvCalc();
    memcpy(&AdsMdl.fusedquat, attitude, 4 * sizeof(double));
    AdsMdl.relquat = AdsMdl.fusedquat;
    AdsStatStruct.AdsStat_DetumblingFlag = resume_sun;
    AdsStatStruct.AdsStat_BdotMethod = finite_difference ? BdotCtrl_Bdot : BdotCtrl_CrossProduct;
    AdsStatStruct.AdsStat_BdotGains.x *= signs[0];
    AdsStatStruct.AdsStat_BdotGains.y *= signs[1];
    AdsStatStruct.AdsStat_BdotGains.z *= signs[2];
    sitlReplaySunTwoDofEnabled = two_dof;
    stateMachine_Init();
}

/* Sensor/model boundary. Angles and magnetic units below match ADS tasks.
 * This exercises dispatch after fault detection, using the real FDIR counters. */
int p30xl_step(uint32_t elapsed_ms, const double sample[27], const int flags[9],
               double output[23], int status[8], int event_trace[24])
{
    Adsquat target = {0};
    tick = elapsed_ms;
    transitions = 0;
    AdsHk.AdsTime = epoch + tick / 1000;
    if (flags[0] && lastGpsPost != AdsHk.AdsTime) {
        stateMachine_PostAbsoluteTime(AdsHk.AdsTime, 1);
        lastGpsPost = AdsHk.AdsTime;
    }
    gpsFusionPositionUsable = flags[1];
    AdsMdl.inEclipse = flags[2];
    fdirErrCnters.StracErrCnt = flags[3] ? 0 : DEFAULT_RETRIES_TOLERATED;
    fdirErrCnters.StracGoodCnt = flags[3] ? STRAC_RECOVERY_GOOD_SOLUTIONS : 0;
    smVars.health.strac = flags[3]; /* ready at this post-FDIR boundary */
    for (int i = 0; i < 3; i++)
        fdirErrCnters.AcsMtrErrCnt[i] = flags[4 + i] ? 0 : DEFAULT_RETRIES_TOLERATED;
    for (int i = 0; i < 4; i++) {
        fdirErrCnters.AcsRwErrCnt[i] = flags[7] ? 0 : DEFAULT_RETRIES_TOLERATED;
        AdsHk.RWTlm[i].currspeed = (uint16_t)round((sample[20 + i] + RW_SPEED_CONV_OFFSET) / RW_SPEED_CONV_SLOPE);
        AdsHkAct.RWTlm[i] = AdsHk.RWTlm[i];
    }
    memcpy(&AdsMdl.PosVectorECI, sample, 3 * sizeof(double));
    memcpy(&AdsMdl.VelVectorECI, sample + 3, 3 * sizeof(double));
    memcpy(&AdsMdl.absquat, sample + 6, 4 * sizeof(double));
    memcpy(&AdsMdl.bodyRate, sample + 10, 3 * sizeof(double));
    memcpy(&AdsMdl.magVectorB, sample + 13, 3 * sizeof(double));
    memcpy(&AdsMdl.magVectorI, sample + 16, 3 * sizeof(double));
    memcpy(&AdsMdl.sunVectorB, sample + 24, 3 * sizeof(double));
    AdsMdl.Wmag = utilsMod(AdsMdl.bodyRate);
    eciSvCalc();
    if (elapsed_ms != 0)
        fuseAttitude(TIME_STEP / 1000.0);
    AdsMdl.relquat = AdsMdl.fusedquat;
    if (flags[8])
        triggerEvent(Event_StartSunPointing);
    controlLoop();
    status[0] = smVars.state;
    status[1] = AdsHk.AdcsMode;
    status[2] = fuseAttDiag.source;
    status[3] = smVars.leopSunPointAchieved;
    status[4] = 0;
    status[5] = 0;
    status[6] = smVars.health.gps;
    status[7] = AdsStatStruct.AdsStat_DetumblingFlag;
    switch (smVars.state) {
    case State_SunPointing_R1:
        target = sunPtR1Vars.qdes;
        break;
    case State_SunPointing_M1:
        target = sunPointingM1Vars.qRef;
        break;
    case State_SunPointing_Search:
        if (flags[7]) {
            target = sunPtR2Vars.sunSearchTgtQuat;
            status[4] = sunPtR2Vars.sunSearchCnt;
            status[5] = sunPtR2Vars.searchMode;
        } else {
            target = sunPtM2Vars.sunSearchTgtQuat;
            status[4] = sunPtM2Vars.sunSearchCnt;
            status[5] = sunPtM2Vars.searchMode;
        }
        break;
    default:
        break;
    }
    memcpy(output, &bdotVars.controlMoment, 3 * sizeof(double));
    for (int i = 0; i < 3; i++)
        output[3 + i] = (cmdActValues.MtrDir[i] ? 1 : -1) * cmdActValues.MtrCurr[i];
    for (int i = 0; i < 4; i++)
        output[6 + i] = (cmdActValues.RwTorque[i] - RW_TORQUE_CONV_OFFSET) / RW_TORQUE_CONV_SLOPE;
    memcpy(output + 10, &AdsMdl.fusedquat, 4 * sizeof(double));
    memcpy(output + 14, &target, 4 * sizeof(double));
    output[18] = smVars.stateEntryTime >= epoch ? smVars.stateEntryTime - epoch : 0;
    output[19] = AdsMdl.Wmag;
    memcpy(output + 20, &AdsMdl.sunVectorI, 3 * sizeof(double));
    memcpy(event_trace, trace, 3 * transitions * sizeof(int));
    return transitions;
}
