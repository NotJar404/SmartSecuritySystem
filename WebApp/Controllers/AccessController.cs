using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using System.Linq;
using System.Threading.Tasks;
using WebApp.Models;
using WebApp.Data;

namespace WebApp.Controllers
{
    public class AccessController : Controller
    {
        private readonly AppDbContext _context;

        public AccessController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // MAIN PAGE
        // =========================
        public async Task<IActionResult> Index()
        {
            var logs = await _context.AccessLogs
                .Include(x => x.Person)
                .Include(x => x.RoomEntity)
                .OrderByDescending(x => x.Timestamp)
                .Take(50)
                .ToListAsync();

            foreach (var log in logs)
            {
                // =========================
                // PERSON MAPPING (REAL FIELDS ONLY)
                // =========================
                log.FullName = log.Person?.FullName;
                log.PersonnelId = log.PersonId?.ToString();
                log.Department = log.Person?.Department;
                log.Email = log.Person?.Email;
                log.Phone = log.Person?.Phone;

                // No ImageUrl in DB → keep default UI image
                log.ImageUrl = "/images/default-user.png";

                // =========================
                // ROOM MAPPING (ONLY ROOM NAME AVAILABLE)
                // =========================
                log.Room = log.RoomEntity?.RoomName;

                // You do NOT have Location column in DB → safe fallback
                log.Location = "Unknown Location";

                // =========================
                // FALLBACK SAFETY (UI ONLY)
                // =========================
                log.FullName ??= "Unknown User";
                log.PersonnelId ??= "N/A";
                log.Department ??= "-";
                log.Email ??= "-";
                log.Phone ??= "-";
                log.Room ??= "Unknown Room";
                log.Location ??= "Unknown Location";
            }

            return View(logs);
        }

        // =========================
        // UNLOCK DOOR (POST)
        // =========================
        [HttpPost]
        public IActionResult UnlockDoor()
        {
            TempData["Message"] = "Door unlocked successfully.";
            return RedirectToAction(nameof(Index));
        }

        // =========================
        // API: GET LATEST LOGS
        // =========================
        [HttpGet]
        public async Task<IActionResult> GetLatestLogs()
        {
            var logs = await _context.AccessLogs
                .Include(x => x.Person)
                .Include(x => x.RoomEntity)
                .OrderByDescending(x => x.Timestamp)
                .Take(20)
                .ToListAsync();

            var result = logs.Select(log => new
            {
                FullName = log.Person?.FullName ?? "Unknown User",
                StudentId = log.PersonId?.ToString() ?? "N/A",

                Department = log.Person?.Department ?? "-",
                Email = log.Person?.Email ?? "-",
                Phone = log.Person?.Phone ?? "-",

                Room = log.RoomEntity?.RoomName ?? "Unknown Room",
                Location = "Unknown Location",

                Time = log.Timestamp.ToString("hh:mm tt"),
                ImageUrl = "/images/default-user.png",
                Status = log.Status
            });

            return Json(result);
        }
    }
}