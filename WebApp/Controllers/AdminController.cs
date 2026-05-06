using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using SmartSecuritySystem.Models;
using SmartSecuritySystem.ViewModels;
using WebApp.Models;
using System;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Net;
using System.Net.Mail;
using System.Security.Cryptography;
using System.Text;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin")]
    public class AdminController : Controller
    {
        private readonly AppDbContext _context;

        public AdminController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // DASHBOARD
        // =========================
        public async Task<IActionResult> Index()
        {
            var model = await BuildDashboardModel();
            ViewBag.Rooms = await _context.Rooms.ToListAsync();
            return View(model);
        }

        // =========================
        // ANALYTICS
        // =========================
        public async Task<IActionResult> Analytics()
        {
            var model = await BuildDashboardModel();
            return View(model);
        }

        // =========================
        // CORE DASHBOARD BUILDER
        // =========================
        private async Task<AdminDashboardViewModel> BuildDashboardModel()
        {
            var now = DateTime.UtcNow;

            var users = await _context.Users
                .Where(u => u.Status == "Active")
                .CountAsync();

            var cameras = await _context.CameraDevices
                .Where(c => c.Status == "active")
                .CountAsync();

            var alertsActive = await _context.Alerts
                .Where(a =>
                    a.Status == AlertStatus.New ||
                    a.Status == AlertStatus.Acknowledged)
                .CountAsync();

            var detectionToday = await _context.DetectionLogs
                .Where(d => d.Timestamp.Date == now.Date)
                .CountAsync();

            var alertDates = await _context.Alerts
                .Select(a => a.Timestamp)
                .ToListAsync();

            var accessDates = await _context.AccessLogs
                .Select(a => a.Timestamp)
                .ToListAsync();

            var motionDates = await _context.DetectionLogs
                .Select(d => d.Timestamp)
                .ToListAsync();

            var occupancy = await SafeLoadRoomOccupancy();

            return new AdminDashboardViewModel
            {
                ActivePersonnelCount = users,
                ActiveCameraCount = cameras,
                ActiveIncidentCount = alertsActive,
                TodayDetectionCount = detectionToday,
                AlertWeekly = GroupByWeek(alertDates),
                AccessWeekly = GroupByWeek(accessDates),
                MotionWeekly = GroupByWeek(motionDates),
                OccupancyWeekly = GroupByWeek(occupancy.Select(o => o.Timestamp)),
                Labels = new List<string>
                {
                    "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
                }
            };
        }

        // =========================
        // SAFE OCCUPANCY LOADER
        // =========================
        private async Task<List<RoomOccupancy>> SafeLoadRoomOccupancy()
        {
            try
            {
                return await _context.RoomOccupancy
                    .AsNoTracking()
                    .ToListAsync();
            }
            catch
            {
                return new List<RoomOccupancy>();
            }
        }

        // =========================
        // WEEK GROUPING
        // =========================
        private List<int> GroupByWeek(IEnumerable<DateTime> dates)
        {
            var grouped = dates
                .GroupBy(d => d.DayOfWeek)
                .ToDictionary(g => g.Key, g => g.Count());

            return new List<int>
            {
                grouped.GetValueOrDefault(DayOfWeek.Monday),
                grouped.GetValueOrDefault(DayOfWeek.Tuesday),
                grouped.GetValueOrDefault(DayOfWeek.Wednesday),
                grouped.GetValueOrDefault(DayOfWeek.Thursday),
                grouped.GetValueOrDefault(DayOfWeek.Friday),
                grouped.GetValueOrDefault(DayOfWeek.Saturday),
                grouped.GetValueOrDefault(DayOfWeek.Sunday)
            };
        }

        // =========================
        // PERSONNEL
        // =========================
        public async Task<IActionResult> Personnel(string? search)
        {
            var users = _context.Users.AsQueryable();
            var members = _context.AuthorizedPersonnel.AsQueryable();

            if (!string.IsNullOrWhiteSpace(search))
            {
                users = users.Where(u =>
                    (u.FullName ?? "").Contains(search) ||
                    (u.Username ?? "").Contains(search) ||
                    (u.Email ?? "").Contains(search));

                members = members.Where(m =>
                    (m.FullName ?? "").Contains(search) ||
                    (m.Email ?? "").Contains(search) ||
                    (m.Department ?? "").Contains(search));
            }

            var userList = await users.ToListAsync();
            var memberList = await members.ToListAsync();

            var campusMembers = memberList.Select(m => new AuthorizedMember
            {
                Id = m.PersonId,
                FullName = m.FullName,
                Email = m.Email ?? "",
                Phone = m.Phone ?? "",
                Department = m.Department ?? "",
                RfidTag = m.RfidTag ?? "",
                Status = m.Status,
                SecurityLevel = m.SecurityLevel,
                HasFaceData = !string.IsNullOrEmpty(m.FaceEmbedding),
                CreatedAt = m.CreatedAt,
                LastAccess = null
            }).ToList();

            var viewModel = new PersonnelManagementViewModel
            {
                SystemUsers = userList,
                CampusMembers = campusMembers
            };

            return View("~/Views/Admin/Personnel.cshtml", viewModel);
        }

        // =========================
        // ADD USER (WITH EMAIL)
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Add(User user, string RegType, string? Department, string? RfidTag, string? Phone)
        {
            if (RegType == "staff")
            {
                if (_context.Users.Any(u => u.Email == user.Email))
                {
                    TempData["Error"] = "Error: Email is already registered.";
                    return RedirectToAction(nameof(Personnel));
                }

                if (_context.Users.Any(u => u.Username == user.Username))
                {
                    TempData["Error"] = "Error: Username is already taken.";
                    return RedirectToAction(nameof(Personnel));
                }

                var tempPassword = GenerateSecurePassword(12);

                user.Role = string.IsNullOrWhiteSpace(user.Role) ? "Security" : user.Role;
                user.Status = "active";
                user.PasswordHash = HashPassword(tempPassword);
                user.MustChangePassword = true;
                user.CreatedAt = DateTime.UtcNow;
                user.UpdatedAt = DateTime.UtcNow;

                _context.Users.Add(user);
                await _context.SaveChangesAsync();

                try
                {
                    await SendCredentialEmail(user.Email, user.FullName, user.Username, tempPassword);
                    TempData["Success"] = "Account created! Temporary password sent to " + user.Email;
                }
                catch (Exception ex)
                {
                    TempData["Error"] = "Account saved, but email failed: " + ex.Message;
                }
            }
            else
            {
                if (string.IsNullOrWhiteSpace(user.FullName) || string.IsNullOrWhiteSpace(RfidTag))
                {
                    TempData["Error"] = "Full name and RFID tag are required.";
                    return RedirectToAction(nameof(Personnel));
                }

                if (_context.AuthorizedPersonnel.Any(p => p.RfidTag == RfidTag))
                {
                    TempData["Error"] = "Error: RFID tag is already registered.";
                    return RedirectToAction(nameof(Personnel));
                }

                var member = new AuthorizedPersonnel
                {
                    FullName = user.FullName,
                    Email = user.Email,
                    Department = Department,
                    RfidTag = RfidTag,
                    Phone = Phone,
                    Status = "active",
                    SecurityLevel = "normal",
                    FaceEmbedding = "PENDING_ENROLLMENT",
                    CreatedAt = DateTime.UtcNow,
                    UpdatedAt = DateTime.UtcNow
                };

                _context.AuthorizedPersonnel.Add(member);
                await _context.SaveChangesAsync();
                TempData["Success"] = "Authorized personnel added successfully.";
            }

            return RedirectToAction(nameof(Personnel));
        }

        // =========================
        // EDIT USER ← BAGO ITO
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Edit(User user, string RegType, string? Department, string? RfidTag, string? Phone)
        {
            if (RegType == "staff")
            {
                var existing = await _context.Users.FindAsync(user.Id);
                if (existing == null)
                {
                    TempData["Error"] = "User not found.";
                    return RedirectToAction(nameof(Personnel));
                }

                existing.FullName = user.FullName;
                existing.Email = user.Email;
                existing.Username = user.Username;
                existing.UpdatedAt = DateTime.UtcNow;

                await _context.SaveChangesAsync();
                TempData["Success"] = "User updated successfully.";
            }
            else
            {
                var existing = await _context.AuthorizedPersonnel.FindAsync(user.Id);
                if (existing == null)
                {
                    TempData["Error"] = "Member not found.";
                    return RedirectToAction(nameof(Personnel));
                }

                existing.FullName = user.FullName;
                existing.Email = user.Email;
                existing.Department = Department;
                existing.RfidTag = RfidTag;
                existing.Phone = Phone;
                existing.UpdatedAt = DateTime.UtcNow;

                await _context.SaveChangesAsync();
                TempData["Success"] = "Member updated successfully.";
            }

            return RedirectToAction(nameof(Personnel));
        }

        // =========================
        // HELPERS
        // =========================
        private string HashPassword(string password)
        {
            using var sha = SHA256.Create();
            return Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(password)));
        }

        private string GenerateSecurePassword(int length)
        {
            const string upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
            const string lower = "abcdefghijkmnopqrstuvwxyz";
            const string digits = "123456789";
            const string special = "!@#$%&*";
            const string all = upper + lower + digits + special;

            var random = new Random();
            var password = new char[length];

            password[0] = upper[random.Next(upper.Length)];
            password[1] = lower[random.Next(lower.Length)];
            password[2] = digits[random.Next(digits.Length)];
            password[3] = special[random.Next(special.Length)];

            for (int i = 4; i < length; i++)
                password[i] = all[random.Next(all.Length)];

            return new string(password.OrderBy(x => random.Next()).ToArray());
        }

        private async Task SendCredentialEmail(string toEmail, string fullName, string username, string tempPassword)
        {
            var fromEmail = "abuanmarden4@gmail.com";
            var appPassword = "womlpksgninuqgty";

            using var client = new SmtpClient("smtp.gmail.com", 587)
            {
                EnableSsl = true,
                Credentials = new NetworkCredential(fromEmail, appPassword)
            };

            var mail = new MailMessage
            {
                From = new MailAddress(fromEmail, "SecureVision System"),
                Subject = "SecureVision — Your Account Credentials",
                Body = $@"
                    <div style='font-family:Arial,sans-serif;max-width:500px;margin:auto;'>
                        <h2 style='color:#d4a373;'>Welcome to SecureVision!</h2>
                        <p>Hello <strong>{fullName}</strong>, your account has been created.</p>
                        <table style='background:#f9f9f9;padding:16px;border-radius:8px;width:100%;'>
                            <tr><td><strong>Username:</strong></td><td>{username}</td></tr>
                            <tr><td><strong>Temporary Password:</strong></td><td style='color:#c43030;'><strong>{tempPassword}</strong></td></tr>
                        </table>
                        <p style='color:#888;margin-top:16px;'>
                            <em>Please log in and change your password immediately.</em>
                        </p>
                        <p style='color:#aaa;font-size:12px;'>SecureVision — Quezon City University</p>
                    </div>",
                IsBodyHtml = true
            };

            mail.To.Add(toEmail);
            await client.SendMailAsync(mail);
        }

        // =========================
        // DELETE USER
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Delete(int id)
        {
            var user = await _context.Users.FindAsync(id);
            if (user == null)
                return NotFound();

            _context.Users.Remove(user);
            await _context.SaveChangesAsync();

            TempData["Success"] = "User deleted successfully.";
            return RedirectToAction(nameof(Personnel));
        }

        // =========================
        // DELETE MEMBER
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> DeleteMember(int id)
        {
            var member = await _context.AuthorizedPersonnel.FindAsync(id);
            if (member == null)
                return NotFound();

            _context.AuthorizedPersonnel.Remove(member);
            await _context.SaveChangesAsync();

            TempData["Success"] = "Member deleted successfully.";
            return RedirectToAction(nameof(Personnel));
        }

        // =========================
        // SYSTEM SETTINGS
        // =========================
        private static SystemStatus systemStatus = new SystemStatus();

        public IActionResult System()
        {
            return View(systemStatus);
        }

        [HttpPost]
        public IActionResult UpdateSetting(string setting, bool value)
        {
            if (string.IsNullOrWhiteSpace(setting))
                return BadRequest();

            switch (setting)
            {
                case "Notifications":
                    systemStatus.NotificationsEnabled = value;
                    break;
                case "Recording":
                    systemStatus.RecordingEnabled = value;
                    break;
                case "AI":
                    systemStatus.AiDetectionEnabled = value;
                    break;
                default:
                    return BadRequest();
            }

            return Ok(new { success = true });
        }
    }
}
