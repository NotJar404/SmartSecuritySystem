using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
using System;
using System.Threading.Tasks;

namespace WebApp.Controllers.Api
{
    [Route("api/rfid")]
    [ApiController]
    public class RfidController : ControllerBase
    {
        private readonly AppDbContext _context;

        public RfidController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // MAIN RFID SCAN ENTRY
        // =========================
        [HttpPost("scan")]
        public async Task<IActionResult> Scan([FromBody] RfidRequest req)
        {
            if (string.IsNullOrEmpty(req?.Uid))
                return BadRequest("Invalid RFID");

            var person = await GetPersonByRfid(req.Uid);

            // =========================
            // SESSION-AWARE DUPLICATE CHECK
            // If person is already inside, do NOT create duplicate log
            // =========================
            if (person != null)
            {
                var activeSession = await _context.OccupancySessions
                    .FirstOrDefaultAsync(s => s.PersonId == person.PersonId
                                           && s.ExitTime == null);

                if (activeSession != null)
                {
                    return Ok(new
                    {
                        status = "already_inside",
                        sessionId = activeSession.SessionId,
                        message = $"{person.FullName} already has an active session"
                    });
                }
            }

            var log = CreateAccessLog(req.Uid, person);

            ApplySecurityRules(req.Uid, log, person);

            _context.AccessLogs.Add(log);

            await _context.SaveChangesAsync();

            return Ok(new { status = log.AccessResult });
        }

        // =========================
        // GET PERSON
        // =========================
        private async Task<AuthorizedPersonnel?> GetPersonByRfid(string uid)
        {
            return await _context.AuthorizedPersonnel
                .FirstOrDefaultAsync(p => p.RfidTag == uid);
        }

        // =========================
        // CREATE ACCESS LOG
        // =========================
        private AccessLog CreateAccessLog(string uid, AuthorizedPersonnel? person)
        {
            return new AccessLog
            {
                PersonId = person?.PersonId,
                AccessResult = person != null ? "granted" : "denied",
                RfidValid = person != null,
                FaceVerified = false,
                Timestamp = DateTime.UtcNow
            };
        }

        // =========================
        // SECURITY RULES (SIMPLE BRAIN)
        // =========================
        private void ApplySecurityRules(string uid, AccessLog log, AuthorizedPersonnel? person)
        {
            // 🚨 Unknown RFID
            if (person == null)
            {
                _context.Notifications.Add(new Notification
                {
                    UserId = null,
                    TargetRole = "Security",
                    Message = $"🚨 Unknown RFID detected: {uid}",
                    IsRead = false,
                    Timestamp = DateTime.UtcNow
                });

                return;
            }

            // 🟡 DENIED ACCESS ALERT (optional future rule)
            if (log.AccessResult == "denied")
            {
                _context.Notifications.Add(new Notification
                {
                    UserId = null,
                    TargetRole = "Admin",
                    Message = $"⚠️ Access denied for {person.FullName}",
                    IsRead = false,
                    Timestamp = DateTime.UtcNow
                });
            }
        }
    }

    // =========================
    // REQUEST MODEL
    // =========================
    public class RfidRequest
    {
        public string? Uid { get; set; }
    }
}