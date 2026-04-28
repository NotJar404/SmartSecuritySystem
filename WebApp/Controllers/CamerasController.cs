using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class CamerasController : Controller
    {
        private readonly AppDbContext _context;

        public CamerasController(AppDbContext context)
        {
            _context = context;
        }

        // ===============================
        // LIVE MONITORING (WITH AUTO-SELECT)
        // ===============================
        public IActionResult Index(int? selectedId)
        {
            LoadRooms();

            // PASS SELECTED CAMERA TO VIEW
            ViewBag.SelectedCameraId = selectedId;

            // AI Metadata: Occupancy counts per camera
            var occupancyCounts = _context.Set<RoomOccupancy>()
                .GroupBy(o => o.CameraId)
                .ToDictionary(g => g.Key, g => g.OrderByDescending(o => o.Timestamp).First().PeopleCount);
            ViewBag.OccupancyCounts = occupancyCounts;

            // AI Metadata: Rooms with active alerts
            var alertRoomIds = _context.Alerts
                .Where(a => a.Status == AlertStatus.New || a.Status == AlertStatus.Acknowledged)
                .Where(a => a.RoomId != null)
                .Select(a => a.RoomId!.Value)
                .ToHashSet();
            ViewBag.CameraAlerts = alertRoomIds;

            return View(GetCameras());
        }

        // ===============================
        // ADD CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(Camera camera)
        {
            LoadRooms();

            if (!ModelState.IsValid)
            {
                return View("Index", GetCameras());
            }

            NormalizeStream(camera);

            if (!IsValidRoom(camera.RoomId))
            {
                ModelState.AddModelError("", "Invalid room selected.");
                return View("Index", GetCameras());
            }

            if (IsDuplicate(camera))
            {
                ModelState.AddModelError("", "Camera already exists in this room.");
                return View("Index", GetCameras());
            }

            try
            {
                camera.Status = "active";

                _context.CameraDevices.Add(camera);
                _context.SaveChanges();

                return RedirectToAction(nameof(Index));
            }
            catch (Exception ex)
            {
                ModelState.AddModelError("", ex.InnerException?.Message ?? ex.Message);
                return View("Index", GetCameras());
            }
        }

        // ===============================
        // EDIT CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Edit(Camera camera)
        {
            LoadRooms();

            if (!ModelState.IsValid)
            {
                return View("Index", GetCameras());
            }

            var existing = _context.CameraDevices.FirstOrDefault(c => c.Id == camera.Id);

            if (existing == null)
                return RedirectToAction(nameof(Index));

            if (!IsValidRoom(camera.RoomId))
            {
                ModelState.AddModelError("", "Invalid room.");
                return View("Index", GetCameras());
            }

            NormalizeStream(camera);

            if (IsDuplicate(camera, true))
            {
                ModelState.AddModelError("", "Duplicate camera found.");
                return View("Index", GetCameras());
            }

            try
            {
                existing.Name = camera.Name;
                existing.RoomId = camera.RoomId;
                existing.StreamUrl = camera.StreamUrl;
                existing.Location = camera.Location;
                existing.Status = string.IsNullOrEmpty(camera.Status) ? "active" : camera.Status;

                _context.SaveChanges();

                return RedirectToAction(nameof(Index));
            }
            catch (Exception ex)
            {
                ModelState.AddModelError("", ex.InnerException?.Message ?? ex.Message);
                return View("Index", GetCameras());
            }
        }

        // ===============================
        // DELETE CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Delete(int id)
        {
            var cam = _context.CameraDevices.FirstOrDefault(c => c.Id == id);

            if (cam != null)
            {
                _context.CameraDevices.Remove(cam);
                _context.SaveChanges();
            }

            return RedirectToAction(nameof(Index));
        }

        // ===============================
        // HELPERS
        // ===============================
        private List<Camera> GetCameras()
        {
            return _context.CameraDevices
                .Include(c => c.Room)
                .ToList();
        }

        private void LoadRooms()
        {
            ViewBag.Rooms = _context.Rooms.ToList();
        }

        private void NormalizeStream(Camera camera)
        {
            if (string.IsNullOrWhiteSpace(camera.StreamUrl))
                camera.StreamUrl = null;
        }

        private bool IsValidRoom(int roomId)
        {
            return _context.Rooms.Any(r => r.RoomId == roomId);
        }

        private bool IsDuplicate(Camera camera, bool isEdit = false)
        {
            return _context.CameraDevices.Any(c =>
                (!isEdit || c.Id != camera.Id) &&
                c.RoomId == camera.RoomId &&
                !string.IsNullOrEmpty(camera.StreamUrl) &&
                c.StreamUrl == camera.StreamUrl
            );
        }
    }
}